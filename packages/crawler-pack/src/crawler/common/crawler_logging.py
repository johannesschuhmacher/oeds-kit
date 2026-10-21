# SPDX-FileCopyrightText: Florian Maurer, Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-crawler file log and rate-limited critical-error mails.

The logger is named after the crawler: the scheduler sends alert mails through
``logging.getLogger(crawler_name).critical`` and the crawler modules' own
``log = logging.getLogger("<crawler>")`` share the same handlers.
"""

import json
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler, SMTPHandler
from pathlib import Path

DEFAULT_EMAIL_RATE_LIMIT_SECONDS = 60 * 60
DEFAULT_LOG_FILE_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_LOG_FILE_BACKUP_COUNT = 5


class RateLimitedSMTPHandler(SMTPHandler):
    """SMTP handler with a persistent per-crawler cooldown."""

    _state_lock = threading.Lock()

    def __init__(
        self,
        *args,
        rate_limit_seconds: int = DEFAULT_EMAIL_RATE_LIMIT_SECONDS,
        rate_limit_key: str,
        state_file: str | os.PathLike[str] = "logs/email_alert_state.json",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.rate_limit_seconds = max(0, int(rate_limit_seconds))
        self.rate_limit_key = rate_limit_key
        self.state_file = Path(state_file)

    def emit(self, record):
        if self._is_rate_limited():
            return
        self._emit_smtp(record)

    def _emit_smtp(self, record):
        super().emit(record)

    def _is_rate_limited(self) -> bool:
        if self.rate_limit_seconds <= 0:
            return False

        now = time.time()
        with self._state_lock:
            state = self._read_state()
            entry = state.get(self.rate_limit_key)
            if isinstance(entry, dict):
                try:
                    last_sent = float(entry.get("last_sent", 0))
                except (TypeError, ValueError):
                    last_sent = 0
                if now - last_sent < self.rate_limit_seconds:
                    return True

            state[self.rate_limit_key] = {"last_sent": now}
            self._write_state(state)
            return False

    def _read_state(self) -> dict:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return state if isinstance(state, dict) else {}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.state_file.with_name(
            f"{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temp_file.write_text(
            json.dumps(state, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_file, self.state_file)


def _email_rate_limit_seconds(email_config: dict) -> int:
    raw_seconds = email_config.get("rate_limit_seconds")
    raw_minutes = email_config.get("rate_limit_minutes")

    if raw_seconds not in (None, ""):
        try:
            return max(0, int(raw_seconds))
        except (TypeError, ValueError):
            return DEFAULT_EMAIL_RATE_LIMIT_SECONDS

    if raw_minutes not in (None, ""):
        try:
            return max(0, int(float(raw_minutes) * 60))
        except (TypeError, ValueError):
            return DEFAULT_EMAIL_RATE_LIMIT_SECONDS

    return DEFAULT_EMAIL_RATE_LIMIT_SECONDS


def _email_recipients(toaddrs) -> list[str]:
    if isinstance(toaddrs, str):
        return [
            item.strip()
            for item in toaddrs.replace(";", ",").split(",")
            if item.strip()
        ]

    if isinstance(toaddrs, (list, tuple, set)):
        return [str(item).strip() for item in toaddrs if str(item).strip()]

    return []


def _parse_nonnegative_int(raw_value, default: int) -> int:
    if raw_value in (None, ""):
        return default
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return default


def _logging_config(config: dict) -> dict:
    raw_config = config.get("logging")
    return raw_config if isinstance(raw_config, dict) else {}


def _log_file_max_bytes(config: dict) -> int:
    env_value = os.getenv("OEDS_LOG_FILE_MAX_BYTES")
    if env_value not in (None, ""):
        return _parse_nonnegative_int(env_value, DEFAULT_LOG_FILE_MAX_BYTES)
    return _parse_nonnegative_int(
        _logging_config(config).get("max_bytes"),
        DEFAULT_LOG_FILE_MAX_BYTES,
    )


def _log_file_backup_count(config: dict) -> int:
    env_value = os.getenv("OEDS_LOG_FILE_BACKUP_COUNT")
    if env_value not in (None, ""):
        return _parse_nonnegative_int(env_value, DEFAULT_LOG_FILE_BACKUP_COUNT)
    return _parse_nonnegative_int(
        _logging_config(config).get("backup_count"),
        DEFAULT_LOG_FILE_BACKUP_COUNT,
    )


def _handler_matches_key(handler: logging.Handler, key: tuple) -> bool:
    if getattr(handler, "_oeds_handler_key", None) == key:
        return True

    if key[0] == "file" and isinstance(handler, logging.FileHandler):
        return str(Path(handler.baseFilename).resolve()) == key[1]

    return False


def _add_unique_handler(
    logger: logging.Logger, handler: logging.Handler, key: tuple
) -> None:
    for existing_handler in list(logger.handlers):
        if key[0] == "smtp" and isinstance(existing_handler, SMTPHandler):
            if (
                isinstance(existing_handler, RateLimitedSMTPHandler)
                and getattr(existing_handler, "_oeds_handler_key", None) == key
            ):
                handler.close()
                return
            logger.removeHandler(existing_handler)
            existing_handler.close()
            continue

        if not _handler_matches_key(existing_handler, key):
            continue

        if isinstance(handler, RateLimitedSMTPHandler) and not isinstance(
            existing_handler, RateLimitedSMTPHandler
        ):
            logger.removeHandler(existing_handler)
            existing_handler.close()
            continue

        if getattr(existing_handler, "_oeds_handler_key", None) == key:
            handler.close()
            return
        existing_handler._oeds_handler_key = key
        handler.close()
        return

    handler._oeds_handler_key = key
    logger.addHandler(handler)


def _add_file_handler(logger: logging.Logger, crawler_name: str, config: dict) -> None:
    log_file_name = f'logs/{crawler_name}.log'
    if not os.path.isfile(log_file_name):
        os.makedirs(os.path.dirname(log_file_name), exist_ok=True)

    try:
        fileHandler = RotatingFileHandler(
            log_file_name,
            maxBytes=_log_file_max_bytes(config),
            backupCount=_log_file_backup_count(config),
        )
    except OSError as exc:
        # Logging must never stop a run. The admin UI and the scheduler share
        # the logs directory; a file created by one container as another user
        # is not writable here, so continue with the root logger only.
        logger.warning("Cannot open %s (%s); continuing without a file log.", log_file_name, exc)
    else:
        if logging.root.handlers: # if basicConfig was called before, use the same formatter
            fileHandler.setFormatter(logging.root.handlers[0].formatter) # use the same formatter as defined in basic config in server.py
        _add_unique_handler(
            logger,
            fileHandler,
            ("file", str(Path(log_file_name).resolve())),
        )


def _add_email_handler(logger: logging.Logger, crawler_name: str, config: dict) -> None:
    try:
        email_config = config['email']
        if not isinstance(email_config, dict):
            return
        mailhost = str(email_config.get('mailhost') or '').strip()
        fromaddr = str(email_config.get('fromaddr') or '').strip()
        toaddrs = _email_recipients(email_config.get('toaddrs'))
        if not mailhost and not fromaddr and not toaddrs:
            return
        missing_fields = [
            field_name
            for field_name, field_value in (
                ("mailhost", mailhost),
                ("fromaddr", fromaddr),
                ("toaddrs", toaddrs),
            )
            if not field_value
        ]
        if missing_fields:
            logger.warning(
                "can't configure Email logging: Missing field(s) %s",
                ", ".join(missing_fields),
            )
            return

        subject_template = email_config.get('subject') or (
            'OEDS Crawler :crawler_name Critical Error Notification'
        )
        subject = str(subject_template).replace(':crawler_name', crawler_name)
        username = str(email_config.get('username') or '').strip()
        password = str(email_config.get('password') or '').strip()
        credentials = (username, password) if username or password else None
        smtp_handler = RateLimitedSMTPHandler(
            mailhost=mailhost,
            fromaddr=fromaddr,
            toaddrs=toaddrs,
            subject=subject,
            credentials=credentials,
            rate_limit_seconds=_email_rate_limit_seconds(email_config),
            rate_limit_key=f"{crawler_name}:{subject}",
        )
        smtp_handler.setLevel(logging.CRITICAL)
        if logging.root.handlers:
            smtp_handler.setFormatter(logging.root.handlers[0].formatter) # use the same formatter as defined in basic config in server.py
        _add_unique_handler(
            logger,
            smtp_handler,
            ("smtp", crawler_name, mailhost, fromaddr, tuple(toaddrs), subject),
        )
    except KeyError as e:
        logger.warning(f"can't configure Email logging: Missing field {e}")


def setup_crawler_logging(crawler_name: str, config: dict) -> logging.Logger:
    """Attach the rotating file log and, if configured, the critical-error mail
    handler to ``logging.getLogger(crawler_name)`` and return that logger."""
    logger = logging.getLogger(crawler_name)
    _add_file_handler(logger, crawler_name, config)
    _add_email_handler(logger, crawler_name, config)
    return logger
