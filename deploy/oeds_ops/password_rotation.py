# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import ascii_lowercase, ascii_uppercase, digits
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_ENV_FILE = ROOT / ".env"
DEFAULT_BITWARDEN_APPDATA_DIR = ROOT / ".bitwarden-cli-oeds"
DEFAULT_PGADMIN_ADMIN_EMAIL = "admin@admin.admin"
DEFAULT_DB_NAME = "opendata"
PASSWORD_SPECIALS = "!-_."
PASSWORD_ALPHABET = ascii_lowercase + ascii_uppercase + digits + PASSWORD_SPECIALS
ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
POSTGREST_SERVICE = "open-postgrest"
GRAFANA_SERVICE = "grafana"
PGADMIN_SERVICE = "pgadmin"
OPEN_DATA_SERVICE = "open-data"
OPTIONAL_ROTATED_SERVICES = ("scheduler", "crawler-admin")
REQUIRED_BITWARDEN_ENV_VARS = ("BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD")
SERVICE_PASSWORD_DEFAULTS = {
    "OEDS_DB_PASSWORD": "opendata",
    "OEDS_READONLY_PASSWORD": "readonly",
    "OEDS_GRAFANA_ADMIN_PASSWORD": "opendata",
    "OEDS_PGADMIN_DEFAULT_PASSWORD": "admin",
}


@dataclass(frozen=True)
class SecretSpec:
    env_key: str
    username: str
    item_label: str
    notes_label: str


SECRET_SPECS = (
    SecretSpec(
        env_key="OEDS_DB_PASSWORD",
        username="opendata",
        item_label="PostgreSQL opendata",
        notes_label="PostgreSQL primary role",
    ),
    SecretSpec(
        env_key="OEDS_READONLY_PASSWORD",
        username="readonly",
        item_label="PostgreSQL readonly",
        notes_label="PostgreSQL readonly role for PostgREST and dashboards",
    ),
    SecretSpec(
        env_key="OEDS_GRAFANA_ADMIN_PASSWORD",
        username="opendata",
        item_label="Grafana admin",
        notes_label="Grafana admin user",
    ),
    SecretSpec(
        env_key="OEDS_PGADMIN_DEFAULT_PASSWORD",
        username=DEFAULT_PGADMIN_ADMIN_EMAIL,
        item_label="pgAdmin admin",
        notes_label="pgAdmin internal admin user",
    ),
)


class RotationError(RuntimeError):
    """Raised when a password rotation step fails."""


class CommandError(RotationError):
    """Raised when an external command fails."""

    def __init__(
        self,
        label: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        message = f"{label} failed with exit code {returncode}."
        if stderr.strip():
            message += f" stderr: {stderr.strip()}"
        elif stdout.strip():
            message += f" stdout: {stdout.strip()}"
        super().__init__(message)
        self.label = label
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rotate the OEDS-internal PostgreSQL, Grafana, and pgAdmin "
            "passwords on a host deployment and write the new credentials to "
            "Bitwarden."
        ),
    )
    parser.add_argument(
        "--compose-env-file",
        type=Path,
        default=DEFAULT_COMPOSE_ENV_FILE,
        help="Path to the compose .env file that stores OEDS runtime settings.",
    )
    parser.add_argument(
        "--deployment-name",
        default=socket.gethostname(),
        help=(
            "Human-readable deployment label used in Bitwarden item names. "
            "Defaults to the current hostname."
        ),
    )
    parser.add_argument(
        "--access-host",
        default=socket.getfqdn() or socket.gethostname(),
        help=(
            "Host or DNS name written into Bitwarden item URIs. Defaults to "
            "the local FQDN."
        ),
    )
    parser.add_argument(
        "--bitwarden-folder",
        default=None,
        help=(
            "Target Bitwarden folder. Defaults to OEDS/<deployment-name>."
        ),
    )
    parser.add_argument(
        "--bitwarden-appdata-dir",
        type=Path,
        default=DEFAULT_BITWARDEN_APPDATA_DIR,
        help=(
            "Dedicated BITWARDENCLI_APPDATA_DIR used for this automation. "
            "Defaults to .bitwarden-cli-oeds in the repository root."
        ),
    )
    parser.add_argument(
        "--docker-bin",
        default="docker",
        help="Docker CLI binary to use. Defaults to docker.",
    )
    parser.add_argument(
        "--bw-bin",
        default="bw",
        help="Bitwarden CLI binary to use. Defaults to bw.",
    )
    parser.add_argument(
        "--password-length",
        type=int,
        default=32,
        help="Generated password length. Defaults to 32.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the plan and validate inputs without changing anything.",
    )
    return parser.parse_args(argv)


def require_binary(binary: str) -> None:
    if shutil.which(binary) is None:
        raise RotationError(
            f"Required binary '{binary}' is not available in PATH."
        )


def generate_password(length: int = 32) -> str:
    if length < 12:
        raise ValueError("Password length must be at least 12 characters.")

    parts = [
        secrets.choice(ascii_lowercase),
        secrets.choice(ascii_uppercase),
        secrets.choice(digits),
        secrets.choice(PASSWORD_SPECIALS),
    ]
    parts.extend(secrets.choice(PASSWORD_ALPHABET) for _ in range(length - 4))
    secrets.SystemRandom().shuffle(parts)
    return "".join(parts)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise RotationError(f"Compose env file does not exist: {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value
    return values


def render_env_file(original_text: str, updates: dict[str, str]) -> str:
    lines = original_text.splitlines()
    updated_keys: set[str] = set()
    rendered: list[str] = []

    for line in lines:
        match = ENV_LINE_RE.match(line)
        if match is None:
            rendered.append(line)
            continue

        key = match.group(1)
        if key in updates:
            rendered.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            rendered.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            rendered.append(f"{key}={value}")

    return "\n".join(rendered).rstrip("\n") + "\n"


def write_secure_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp_path, mode)
    except OSError:
        pass
    os.replace(tmp_path, path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def make_backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    return path.with_name(f"{path.name}.bak-{timestamp}")


def make_pending_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    return path.with_name(f".oeds-password-rotation.pending-{timestamp}.json")


def create_backup_file(path: Path) -> Path:
    backup_path = make_backup_path(path)
    shutil.copy2(path, backup_path)
    try:
        os.chmod(backup_path, 0o600)
    except OSError:
        pass
    return backup_path


def compose_port(env_map: dict[str, str], key: str, default: str) -> str:
    return env_map.get(key, default)


def current_passwords(env_map: dict[str, str]) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for env_key, default in SERVICE_PASSWORD_DEFAULTS.items():
        passwords[env_key] = env_map.get(env_key, default)
    return passwords


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    label: str,
) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise CommandError(
            label=label,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout


def http_get(
    url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, str]:
    request = Request(url)
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except URLError as exc:
        raise RotationError(f"HTTP request to {url} failed: {exc}") from exc


def retry(step_name: str, func: Any, attempts: int = 20, delay: float = 2.0) -> Any:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - exercised indirectly
            last_error = exc
            time.sleep(delay)
    if last_error is None:
        raise RotationError(f"{step_name} failed without an error.")
    raise RotationError(f"{step_name} did not succeed: {last_error}") from last_error


def pgadmin_setup_script() -> str:
    return """
if [ -x /venv/bin/python ] && [ -f /pgadmin4/setup.py ]; then
  exec /venv/bin/python /pgadmin4/setup.py "$@"
fi
if command -v pgadmin4-cli >/dev/null 2>&1; then
  exec pgadmin4-cli "$@"
fi
if command -v python3 >/dev/null 2>&1 && [ -f /pgadmin4/setup.py ]; then
  exec python3 /pgadmin4/setup.py "$@"
fi
if command -v python >/dev/null 2>&1 && [ -f /pgadmin4/setup.py ]; then
  exec python /pgadmin4/setup.py "$@"
fi
echo "Unable to find a pgAdmin setup.py runner inside the container." >&2
exit 1
""".strip()


class BitwardenSession:
    def __init__(
        self,
        *,
        bw_bin: str,
        appdata_dir: Path,
        server_url: str | None,
        folder_name: str,
    ) -> None:
        self.bw_bin = bw_bin
        self.appdata_dir = appdata_dir
        self.server_url = server_url
        self.folder_name = folder_name
        self.session_key: str | None = None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["BITWARDENCLI_APPDATA_DIR"] = str(self.appdata_dir)
        if self.session_key:
            env["BW_SESSION"] = self.session_key
        return env

    def _run(
        self,
        args: list[str],
        *,
        label: str,
        input_text: str | None = None,
    ) -> str:
        return run_command(
            [self.bw_bin, *args],
            env=self._env(),
            input_text=input_text,
            label=label,
        )

    def prepare(self) -> None:
        require_binary(self.bw_bin)
        for env_key in REQUIRED_BITWARDEN_ENV_VARS:
            if not os.getenv(env_key):
                raise RotationError(
                    f"Bitwarden environment variable {env_key} is required."
                )

        self.appdata_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.appdata_dir, 0o700)
        except OSError:
            pass

        try:
            self._run(["logout", "--nointeraction"], label="Bitwarden logout")
        except RotationError:
            pass

        if self.server_url:
            self._run(
                ["config", "server", self.server_url],
                label="Bitwarden server configuration",
            )

        self._run(
            ["login", "--apikey", "--nointeraction"],
            label="Bitwarden API-key login",
        )
        self.session_key = self._run(
            [
                "unlock",
                "--passwordenv",
                "BW_PASSWORD",
                "--raw",
                "--nointeraction",
            ],
            label="Bitwarden vault unlock",
        ).strip()
        self._run(["sync"], label="Bitwarden vault sync")

    def close(self) -> None:
        try:
            self._run(["lock", "--nointeraction"], label="Bitwarden lock")
        except RotationError:
            pass
        try:
            self._run(["logout", "--nointeraction"], label="Bitwarden logout")
        except RotationError:
            pass
        self.session_key = None

    def ensure_folder(self) -> str:
        folders = json.loads(
            self._run(["list", "folders"], label="Bitwarden folder list")
        )
        for folder in folders:
            if folder.get("name") == self.folder_name:
                return str(folder["id"])

        payload = base64.b64encode(
            json.dumps({"name": self.folder_name}).encode("utf-8")
        ).decode("ascii")
        created = json.loads(
            self._run(
                ["create", "folder", payload],
                label="Bitwarden folder creation",
            )
        )
        return str(created["id"])

    def upsert_login_item(
        self,
        *,
        item_name: str,
        username: str,
        password: str,
        notes: str,
        folder_id: str,
        uri: str,
    ) -> None:
        candidates = json.loads(
            self._run(
                ["list", "items", "--search", item_name],
                label=f"Bitwarden search for {item_name}",
            )
        )
        matches = [
            item
            for item in candidates
            if item.get("name") == item_name and item.get("folderId") == folder_id
        ]
        if len(matches) > 1:
            raise RotationError(
                f"Multiple Bitwarden items named '{item_name}' exist in folder "
                f"{self.folder_name}. Clean that up before rotating."
            )

        if matches:
            item_id = str(matches[0]["id"])
            item = json.loads(
                self._run(["get", "item", item_id], label=f"Bitwarden get {item_name}")
            )
            login = item.setdefault("login", {})
            item["name"] = item_name
            item["folderId"] = folder_id
            item["notes"] = notes
            login["username"] = username
            login["password"] = password
            login["uris"] = [{"uri": uri}]
            payload = base64.b64encode(
                json.dumps(item).encode("utf-8")
            ).decode("ascii")
            self._run(
                ["edit", "item", item_id, payload],
                label=f"Bitwarden edit {item_name}",
            )
            return

        item_template = json.loads(
            self._run(["get", "template", "item"], label="Bitwarden item template")
        )
        login_template = json.loads(
            self._run(
                ["get", "template", "item.login"],
                label="Bitwarden login template",
            )
        )
        item_template["name"] = item_name
        item_template["folderId"] = folder_id
        item_template["notes"] = notes
        login_template["username"] = username
        login_template["password"] = password
        login_template["uris"] = [{"uri": uri}]
        item_template["login"] = login_template

        payload = base64.b64encode(
            json.dumps(item_template).encode("utf-8")
        ).decode("ascii")
        self._run(
            ["create", "item", payload],
            label=f"Bitwarden create {item_name}",
        )


class PasswordRotator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.compose_env_path = args.compose_env_file.resolve()
        self.repo_root = self.compose_env_path.parent
        self.folder_name = args.bitwarden_folder or f"OEDS/{args.deployment_name}"
        self.compose_env_text = self.compose_env_path.read_text(encoding="utf-8")
        self.compose_env = load_env_file(self.compose_env_path)
        self.old_passwords = current_passwords(self.compose_env)
        self.new_passwords = {
            spec.env_key: generate_password(args.password_length)
            for spec in SECRET_SPECS
        }
        self.pending_file = make_pending_path(self.compose_env_path)
        self.backup_file: Path | None = None
        self.bitwarden = BitwardenSession(
            bw_bin=args.bw_bin,
            appdata_dir=args.bitwarden_appdata_dir.resolve(),
            server_url=os.getenv("BW_SERVER_URL"),
            folder_name=self.folder_name,
        )

    def compose_command(self, *args: str, label: str) -> str:
        return run_command(
            [self.args.docker_bin, "compose", *args],
            cwd=self.repo_root,
            label=label,
        )

    def docker_exec(self, *args: str, label: str) -> str:
        return run_command([self.args.docker_bin, "exec", *args], label=label)

    def create_pending_file(self) -> None:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "deployment_name": self.args.deployment_name,
            "compose_env_file": str(self.compose_env_path),
            "passwords": self.new_passwords,
        }
        write_secure_text(
            self.pending_file,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )

    def check_stack_state(self) -> list[str]:
        running = [
            line.strip()
            for line in self.compose_command(
                "ps",
                "--status",
                "running",
                "--services",
                label="Docker Compose service discovery",
            ).splitlines()
            if line.strip()
        ]
        required = {OPEN_DATA_SERVICE, GRAFANA_SERVICE, PGADMIN_SERVICE}
        missing = sorted(required.difference(running))
        if missing:
            raise RotationError(
                "The OEDS stack is not fully running. Missing services: "
                + ", ".join(missing)
            )
        return running

    def rotate_database_passwords(self, passwords: dict[str, str]) -> None:
        for role_name, env_key in (
            ("opendata", "OEDS_DB_PASSWORD"),
            ("readonly", "OEDS_READONLY_PASSWORD"),
        ):
            self.docker_exec(
                "-u",
                "postgres",
                OPEN_DATA_SERVICE,
                "psql",
                "-d",
                DEFAULT_DB_NAME,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"ALTER ROLE {role_name} PASSWORD '{passwords[env_key]}';",
                label=f"Rotate PostgreSQL password for role {role_name}",
            )

    def rotate_grafana_password(self, password: str) -> None:
        self.docker_exec(
            GRAFANA_SERVICE,
            "grafana",
            "cli",
            "--homepath",
            "/usr/share/grafana",
            "--config",
            "/etc/grafana/grafana.ini",
            "admin",
            "reset-admin-password",
            password,
            label="Rotate Grafana admin password",
        )

    def run_pgadmin_setup(self, *args: str, label: str) -> str:
        return self.docker_exec(
            PGADMIN_SERVICE,
            "sh",
            "-lc",
            pgadmin_setup_script(),
            "sh",
            *args,
            label=label,
        )

    def rotate_pgadmin_password(self, password: str) -> None:
        self.run_pgadmin_setup(
            "update-user",
            DEFAULT_PGADMIN_ADMIN_EMAIL,
            "--password",
            password,
            label="Rotate pgAdmin admin password",
        )

    def write_new_compose_env(self) -> None:
        updated_text = render_env_file(self.compose_env_text, self.new_passwords)
        write_secure_text(self.compose_env_path, updated_text, mode=0o600)

    def restore_compose_env(self) -> None:
        write_secure_text(self.compose_env_path, self.compose_env_text, mode=0o600)

    def restart_dependent_services(self, running_services: list[str]) -> None:
        services = [POSTGREST_SERVICE, GRAFANA_SERVICE, PGADMIN_SERVICE]
        services.extend(
            service
            for service in OPTIONAL_ROTATED_SERVICES
            if service in running_services
        )
        self.compose_command(
            "up",
            "-d",
            "--no-deps",
            *services,
            label="Restart OEDS services that consume rotated passwords",
        )

    def verify_database_login(self, role_name: str, password: str) -> None:
        output = self.docker_exec(
            "-e",
            f"PGPASSWORD={password}",
            OPEN_DATA_SERVICE,
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            role_name,
            "-d",
            DEFAULT_DB_NAME,
            "-tAc",
            "SELECT 1;",
            label=f"Verify PostgreSQL login for role {role_name}",
        )
        if output.strip() != "1":
            raise RotationError(
                f"Verification query for PostgreSQL role {role_name} failed."
            )

    def verify_postgrest(self) -> None:
        port = compose_port(self.compose_env, "OEDS_POSTGREST_PORT", "3001")
        status, _ = http_get(f"http://127.0.0.1:{port}/")
        if status != 200:
            raise RotationError(f"PostgREST health check returned HTTP {status}.")

    def verify_grafana(self) -> None:
        port = compose_port(self.compose_env, "OEDS_GRAFANA_PORT", "3006")
        status, _ = http_get(
            f"http://127.0.0.1:{port}/api/user",
            username="opendata",
            password=self.new_passwords["OEDS_GRAFANA_ADMIN_PASSWORD"],
        )
        if status != 200:
            raise RotationError(f"Grafana API check returned HTTP {status}.")

    def verify_pgadmin(self) -> None:
        port = compose_port(self.compose_env, "OEDS_PGADMIN_HTTP_PORT", "8080")
        status, _ = http_get(f"http://127.0.0.1:{port}/login")
        if status != 200:
            raise RotationError(f"pgAdmin login page returned HTTP {status}.")

        output = self.run_pgadmin_setup(
            "get-users",
            "--username",
            DEFAULT_PGADMIN_ADMIN_EMAIL,
            "--json",
            label="Verify pgAdmin user listing",
        )
        if DEFAULT_PGADMIN_ADMIN_EMAIL not in output:
            raise RotationError("pgAdmin admin user could not be read after restart.")

    def verify(self) -> None:
        retry(
            "PostgreSQL opendata verification",
            lambda: self.verify_database_login(
                "opendata", self.new_passwords["OEDS_DB_PASSWORD"]
            ),
        )
        retry(
            "PostgreSQL readonly verification",
            lambda: self.verify_database_login(
                "readonly", self.new_passwords["OEDS_READONLY_PASSWORD"]
            ),
        )
        retry("PostgREST verification", self.verify_postgrest)
        retry("Grafana verification", self.verify_grafana)
        retry("pgAdmin verification", self.verify_pgadmin)

    def wallet_uri(self, spec: SecretSpec) -> str:
        postgres_port = compose_port(self.compose_env, "OEDS_POSTGRES_PORT", "6432")
        grafana_port = compose_port(self.compose_env, "OEDS_GRAFANA_PORT", "3006")
        pgadmin_port = compose_port(self.compose_env, "OEDS_PGADMIN_HTTP_PORT", "8080")
        if spec.env_key in {"OEDS_DB_PASSWORD", "OEDS_READONLY_PASSWORD"}:
            return (
                f"postgresql://{self.args.access_host}:{postgres_port}/"
                f"{DEFAULT_DB_NAME}"
            )
        if spec.env_key == "OEDS_GRAFANA_ADMIN_PASSWORD":
            return f"http://{self.args.access_host}:{grafana_port}/login"
        return f"http://{self.args.access_host}:{pgadmin_port}/login"

    def wallet_notes(self, spec: SecretSpec) -> str:
        return "\n".join(
            [
                "Managed by scripts/rotate_oeds_passwords.py",
                f"Deployment: {self.args.deployment_name}",
                f"Hostname: {socket.gethostname()}",
                f"Compose env file: {self.compose_env_path}",
                f"Purpose: {spec.notes_label}",
                f"Updated at: {datetime.now(timezone.utc).isoformat()}",
            ]
        )

    def write_bitwarden_items(self, passwords: dict[str, str] | None = None) -> None:
        password_map = passwords or self.new_passwords
        folder_id = self.bitwarden.ensure_folder()
        for spec in SECRET_SPECS:
            self.bitwarden.upsert_login_item(
                item_name=f"OEDS {self.args.deployment_name} {spec.item_label}",
                username=spec.username,
                password=password_map[spec.env_key],
                notes=self.wallet_notes(spec),
                folder_id=folder_id,
                uri=self.wallet_uri(spec),
            )

    def rollback(self, running_services: list[str]) -> None:
        logging.warning("Rolling back rotated passwords to their previous values.")
        self.rotate_database_passwords(self.old_passwords)
        self.rotate_grafana_password(self.old_passwords["OEDS_GRAFANA_ADMIN_PASSWORD"])
        self.rotate_pgadmin_password(self.old_passwords["OEDS_PGADMIN_DEFAULT_PASSWORD"])
        self.restore_compose_env()
        self.restart_dependent_services(running_services)
        try:
            self.write_bitwarden_items(self.old_passwords)
        except Exception as exc:
            logging.error("Bitwarden rollback failed: %s", exc)

    def run(self) -> int:
        require_binary(self.args.docker_bin)
        logging.info("Using compose env file %s", self.compose_env_path)
        logging.info("Target Bitwarden folder: %s", self.folder_name)

        if self.args.dry_run:
            logging.info("Dry run only. The following secret keys would rotate:")
            for spec in SECRET_SPECS:
                logging.info(
                    "  %s -> OEDS %s %s",
                    spec.env_key,
                    self.args.deployment_name,
                    spec.item_label,
                )
            return 0

        running_services = self.check_stack_state()
        self.bitwarden.prepare()
        try:
            self.backup_file = create_backup_file(self.compose_env_path)
            self.create_pending_file()

            try:
                self.rotate_database_passwords(self.new_passwords)
                self.rotate_grafana_password(
                    self.new_passwords["OEDS_GRAFANA_ADMIN_PASSWORD"]
                )
                self.rotate_pgadmin_password(
                    self.new_passwords["OEDS_PGADMIN_DEFAULT_PASSWORD"]
                )
                self.write_new_compose_env()
                self.compose_env = load_env_file(self.compose_env_path)
                self.restart_dependent_services(running_services)
                self.verify()
                self.write_bitwarden_items()
            except Exception:
                try:
                    self.rollback(running_services)
                except Exception as rollback_error:
                    logging.error("Rollback failed: %s", rollback_error)
                    logging.error(
                        "The pending secrets remain in %s for manual recovery.",
                        self.pending_file,
                    )
                raise
            else:
                self.pending_file.unlink(missing_ok=True)
                logging.info("Password rotation finished successfully.")
                if self.backup_file is not None:
                    logging.info("Previous compose env backup: %s", self.backup_file)
                return 0
        finally:
            self.bitwarden.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    try:
        return PasswordRotator(args).run()
    except Exception as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
