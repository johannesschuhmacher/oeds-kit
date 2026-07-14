# SPDX-FileCopyrightText: OEDS Contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import smtplib
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r"""
    name: oeds_mail
    type: notification
    short_description: Send an OEDS playbook status mail after Ansible runs.
    description:
      - Sends one status mail at the end of an Ansible playbook run.
      - The callback is inactive until SMTP host, sender, and recipients are configured.
      - Runtime failures and unreachable hosts are reported as failed runs.
    requirements:
      - Python standard library only.
"""


TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
DEFAULT_SUBJECT = "OEDS Ansible {status}: {playbook}"
DEFAULT_EMAIL_RATE_LIMIT_SECONDS = 60 * 60


@dataclass(frozen=True)
class MailConfig:
    enabled: bool
    mailhost: str
    port: int
    fromaddr: str
    toaddrs: tuple[str, ...]
    subject_template: str
    username: str
    password: str
    use_starttls: bool
    use_ssl: bool
    timeout: float
    dry_run: bool
    dry_run_file: str
    rate_limit_seconds: int
    rate_limit_state_file: str


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "oeds_mail"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self) -> None:
        super().__init__()
        self.started_at = datetime.now(timezone.utc)
        self.playbook_path = ""
        self.playbook_name = "unknown playbook"
        self.failures: list[str] = []
        self.unreachable: list[str] = []
        self._config: MailConfig | None = None

    def v2_playbook_on_start(self, playbook: Any) -> None:
        self.started_at = datetime.now(timezone.utc)
        raw_path = getattr(playbook, "_file_name", None) or getattr(playbook, "file_name", None) or ""
        self.playbook_path = str(raw_path)
        self.playbook_name = Path(str(raw_path)).name if raw_path else "unknown playbook"

    def v2_runner_on_failed(self, result: Any, ignore_errors: bool = False) -> None:
        if ignore_errors:
            return
        self.failures.append(self._format_result("failed", result))

    def v2_runner_on_unreachable(self, result: Any) -> None:
        self.unreachable.append(self._format_result("unreachable", result))

    def v2_playbook_on_stats(self, stats: Any) -> None:
        config = self._mail_config()
        if not config.enabled:
            return

        finished_at = datetime.now(timezone.utc)
        host_rows = self._host_summary(stats)
        failed = any(row["failures"] or row["unreachable"] for row in host_rows)
        status = "FAILED" if failed else "SUCCESS"
        subject = config.subject_template.format(
            status=status,
            playbook=self.playbook_name,
            host=socket.gethostname(),
        )
        body = self._message_body(status, finished_at, host_rows)
        if _is_rate_limited(config, subject):
            return

        try:
            self._send_message(config, subject, body)
        except Exception as exc:  # pragma: no cover - must never fail the playbook result
            self._display.warning(f"OEDS status mail could not be sent: {exc}")

    def _mail_config(self) -> MailConfig:
        if self._config is not None:
            return self._config

        _load_crawler_dotenv()
        explicit_enabled = _get_bool("OEDS_ANSIBLE_EMAIL_ENABLED", "OEDS_ANSIBLE_MAIL_ENABLED", default=None)
        use_ssl = _get_bool("OEDS_ANSIBLE_EMAIL_SSL", "OEDS_ANSIBLE_MAIL_SSL", default=False)
        mailhost_raw = _get_env(
            "OEDS_ANSIBLE_EMAIL_MAILHOST",
            "OEDS_ANSIBLE_MAILHOST",
            "OEDS_EMAIL_MAILHOST",
            default="",
        )
        mailhost, port = _parse_mailhost(
            mailhost_raw,
            int(_get_env("OEDS_ANSIBLE_EMAIL_PORT", "OEDS_ANSIBLE_MAIL_PORT", default="0") or "0"),
            use_ssl=use_ssl,
        )
        fromaddr = _get_env(
            "OEDS_ANSIBLE_EMAIL_FROMADDR",
            "OEDS_ANSIBLE_MAIL_FROMADDR",
            "OEDS_EMAIL_FROMADDR",
            default="",
        )
        toaddrs = _parse_recipients(
            _get_env(
                "OEDS_ANSIBLE_EMAIL_TOADDRS",
                "OEDS_ANSIBLE_MAIL_TOADDRS",
                "OEDS_EMAIL_TOADDRS",
                default="",
            )
        )
        subject_template = _get_env(
            "OEDS_ANSIBLE_EMAIL_SUBJECT",
            "OEDS_ANSIBLE_MAIL_SUBJECT",
            default=DEFAULT_SUBJECT,
        )
        username = _get_env(
            "OEDS_ANSIBLE_EMAIL_USERNAME",
            "OEDS_ANSIBLE_MAIL_USERNAME",
            "OEDS_EMAIL_USERNAME",
            default="",
        )
        password = _get_env(
            "OEDS_ANSIBLE_EMAIL_PASSWORD",
            "OEDS_ANSIBLE_MAIL_PASSWORD",
            "OEDS_EMAIL_PASSWORD",
            default="",
        )
        auto_enabled = bool(mailhost and fromaddr and toaddrs)
        enabled = auto_enabled if explicit_enabled is None else explicit_enabled
        if enabled and not auto_enabled:
            self._display.warning(
                "OEDS status mail is enabled but mailhost, fromaddr, or toaddrs is missing; no mail will be sent."
            )
            enabled = False

        self._config = MailConfig(
            enabled=enabled,
            mailhost=mailhost,
            port=port,
            fromaddr=fromaddr,
            toaddrs=tuple(toaddrs),
            subject_template=subject_template,
            username=username,
            password=password,
            use_starttls=_get_bool("OEDS_ANSIBLE_EMAIL_STARTTLS", "OEDS_ANSIBLE_MAIL_STARTTLS", default=False),
            use_ssl=use_ssl,
            timeout=float(_get_env("OEDS_ANSIBLE_EMAIL_TIMEOUT", "OEDS_ANSIBLE_MAIL_TIMEOUT", default="15")),
            dry_run=_get_bool("OEDS_ANSIBLE_EMAIL_DRY_RUN", "OEDS_ANSIBLE_MAIL_DRY_RUN", default=False),
            dry_run_file=_get_env(
                "OEDS_ANSIBLE_EMAIL_DRY_RUN_FILE",
                "OEDS_ANSIBLE_MAIL_DRY_RUN_FILE",
                default="",
            ),
            rate_limit_seconds=_get_rate_limit_seconds(
                seconds_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS", "OEDS_ANSIBLE_MAIL_RATE_LIMIT_SECONDS"),
                minutes_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES", "OEDS_ANSIBLE_MAIL_RATE_LIMIT_MINUTES"),
                default=DEFAULT_EMAIL_RATE_LIMIT_SECONDS,
            ),
            rate_limit_state_file=_get_env(
                "OEDS_ANSIBLE_EMAIL_RATE_LIMIT_STATE_FILE",
                "OEDS_ANSIBLE_MAIL_RATE_LIMIT_STATE_FILE",
                "OEDS_ANSIBLE_EMAIL_RATE_LIMIT_FILE",
                "OEDS_ANSIBLE_MAIL_RATE_LIMIT_FILE",
                default=_default_rate_limit_state_file(),
            ),
        )
        return self._config

    def _host_summary(self, stats: Any) -> list[dict[str, int | str]]:
        rows: list[dict[str, int | str]] = []
        for host in sorted(stats.processed):
            summary = stats.summarize(host)
            rows.append(
                {
                    "host": host,
                    "ok": int(summary.get("ok", 0)),
                    "changed": int(summary.get("changed", 0)),
                    "unreachable": int(summary.get("unreachable", 0)),
                    "failures": int(summary.get("failures", 0)),
                    "skipped": int(summary.get("skipped", 0)),
                    "rescued": int(summary.get("rescued", 0)),
                    "ignored": int(summary.get("ignored", 0)),
                }
            )
        return rows

    def _message_body(self, status: str, finished_at: datetime, host_rows: list[dict[str, int | str]]) -> str:
        duration_seconds = int((finished_at - self.started_at).total_seconds())
        lines = [
            f"Status: {status}",
            f"Playbook: {self.playbook_name}",
            f"Path: {self.playbook_path or '-'}",
            f"Started: {self.started_at.isoformat()}",
            f"Finished: {finished_at.isoformat()}",
            f"Duration: {duration_seconds}s",
            f"Control host: {socket.gethostname()}",
            f"Control user: {getpass.getuser()}",
            "",
            "Host summary:",
        ]
        for row in host_rows:
            lines.append(
                "  {host}: ok={ok} changed={changed} unreachable={unreachable} "
                "failed={failures} skipped={skipped} rescued={rescued} ignored={ignored}".format(**row)
            )

        details = [*self.unreachable, *self.failures]
        if details:
            lines.extend(["", "Failure details:"])
            lines.extend(f"  - {detail}" for detail in details[:20])
            if len(details) > 20:
                lines.append(f"  - ... {len(details) - 20} further failure(s) omitted")

        lines.extend(["", "Generated by the OEDS Ansible mail callback."])
        return "\n".join(lines) + "\n"

    def _send_message(self, config: MailConfig, subject: str, body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = config.fromaddr
        message["To"] = ", ".join(config.toaddrs)
        message.set_content(body)

        if config.dry_run:
            rendered = message.as_string()
            if config.dry_run_file:
                dry_run_path = Path(config.dry_run_file)
                dry_run_path.parent.mkdir(parents=True, exist_ok=True)
                dry_run_path.write_text(rendered, encoding="utf-8")
            self._display.display(f"OEDS status mail dry-run: {subject}")
            return

        smtp_class = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
        with smtp_class(config.mailhost, config.port, timeout=config.timeout) as server:
            if config.use_starttls and not config.use_ssl:
                server.starttls()
            if config.username or config.password:
                server.login(config.username, config.password)
            server.send_message(message)

    def _format_result(self, state: str, result: Any) -> str:
        host = getattr(getattr(result, "_host", None), "get_name", lambda: "unknown-host")()
        task = getattr(getattr(result, "_task", None), "get_name", lambda: "unknown task")()
        payload = getattr(result, "_result", {}) or {}
        message = payload.get("msg") or payload.get("stderr") or payload.get("stdout") or str(payload)
        message = re.sub(r"\s+", " ", str(message)).strip()
        return f"{host}: {task} {state}: {message[:500]}"


def _load_crawler_dotenv() -> None:
    if _get_bool("OEDS_ANSIBLE_EMAIL_LOAD_CRAWLER_ENV", "OEDS_ANSIBLE_MAIL_LOAD_CRAWLER_ENV", default=True) is False:
        return
    env_path = Path(__file__).resolve().parents[2] / "crawler" / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in os.environ:
            continue
        os.environ[key] = _unquote_env_value(value.strip())


def _get_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _get_bool(*names: str, default: bool | None) -> bool | None:
    raw_value = _get_env(*names, default="")
    if raw_value == "":
        return default
    value = raw_value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return default


def _get_rate_limit_seconds(*, seconds_names: tuple[str, ...], minutes_names: tuple[str, ...], default: int) -> int:
    raw_seconds = _get_env(*seconds_names, default="")
    if raw_seconds:
        try:
            return max(0, int(raw_seconds))
        except (TypeError, ValueError):
            return default

    raw_minutes = _get_env(*minutes_names, default="")
    if raw_minutes:
        try:
            return max(0, int(float(raw_minutes) * 60))
        except (TypeError, ValueError):
            return default

    return default


def _parse_recipients(raw_recipients: str) -> list[str]:
    return [token.strip() for token in re.split(r"[,\n;]+", raw_recipients) if token.strip()]


def _parse_mailhost(raw_mailhost: str, configured_port: int, *, use_ssl: bool) -> tuple[str, int]:
    candidate = raw_mailhost.strip()
    if not candidate:
        return "", configured_port or (465 if use_ssl else 25)
    if candidate.count(":") == 1:
        host, raw_port = candidate.rsplit(":", 1)
        if raw_port.isdigit():
            return host, configured_port or int(raw_port)
    return candidate, configured_port or (465 if use_ssl else 25)


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _default_rate_limit_state_file() -> str:
    return str(Path.home() / ".cache" / "oeds" / "ansible_mail_state.json")


def _rate_limit_key(config: MailConfig, subject: str) -> str:
    raw_key = "\0".join(
        [
            config.mailhost,
            config.fromaddr,
            ",".join(config.toaddrs),
            subject,
        ]
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _is_rate_limited(config: MailConfig, subject: str) -> bool:
    if config.rate_limit_seconds <= 0:
        return False

    state_path = Path(config.rate_limit_state_file).expanduser()
    key = _rate_limit_key(config, subject)
    now = time.time()

    try:
        state = _read_rate_limit_state(state_path)
        entry = state.get(key)
        if isinstance(entry, dict):
            try:
                last_sent = float(entry.get("last_sent", 0))
            except (TypeError, ValueError):
                last_sent = 0
            if now - last_sent < config.rate_limit_seconds:
                return True

        state[key] = {
            "last_sent": now,
            "subject": subject[:200],
        }
        _write_rate_limit_state(state_path, state)
    except OSError:
        return False

    return False


def _read_rate_limit_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def _write_rate_limit_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(state, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_path, path)
