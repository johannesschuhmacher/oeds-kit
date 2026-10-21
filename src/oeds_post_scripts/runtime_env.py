# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Database URI and ``.env`` helpers for post-run scripts.

This mirrors ``crawler.common.runtime_env`` from oeds-crawler-pack so that the
post-scripts need no crawler package at runtime. Keep the override semantics
identical to the pack: the same ``OEDS_DB_*`` variables must reach the same
database from crawlers and post-run commands alike.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

_LOADED_DOTENV_PATHS: set[Path] = set()


def load_crawler_dotenv(path: str | Path | None = None) -> Path | None:
    """Load the crawler ``.env`` file once, without overriding existing variables.

    ``OEDS_CRAWLER_ENV`` names the file to load; otherwise ``path`` is used, and
    without ``path`` the file defaults to ``<cwd>/crawler/.env``. Returns the
    loaded path, or ``None`` when the file does not exist.
    """
    env_path = Path(os.getenv("OEDS_CRAWLER_ENV") or path or Path.cwd() / "crawler" / ".env")
    env_path = env_path.expanduser().resolve()
    if not env_path.exists():
        return None
    if env_path not in _LOADED_DOTENV_PATHS:
        load_dotenv(dotenv_path=env_path, override=False)
        _LOADED_DOTENV_PATHS.add(env_path)
    return env_path


def resolve_database_uri(database_uri: str) -> str:
    """Apply ``OEDS_DB_HOST``, ``OEDS_DB_PORT`` and ``OEDS_DB_PASSWORD`` to a URI."""
    if not isinstance(database_uri, str) or not database_uri.strip():
        return database_uri

    host_override = os.getenv("OEDS_DB_HOST", "").strip()
    port_override = os.getenv("OEDS_DB_PORT", "").strip()
    password_override = os.getenv("OEDS_DB_PASSWORD")
    if password_override is not None:
        password_override = password_override.strip() or None

    if not host_override and not port_override and password_override is None:
        return database_uri

    split = urlsplit(database_uri)
    if not split.scheme or not split.netloc:
        return database_uri

    username = split.username or ""
    password = split.password
    hostname = split.hostname or ""
    port = split.port

    resolved_host = host_override or hostname
    resolved_port = int(port_override) if port_override else port
    resolved_password = quote(password_override, safe="") if password_override is not None else password

    if ":" in resolved_host and not resolved_host.startswith("["):
        host_token = f"[{resolved_host}]"
    else:
        host_token = resolved_host

    auth_token = ""
    if username:
        auth_token = username
        if resolved_password is not None:
            auth_token += f":{resolved_password}"
        auth_token += "@"

    netloc = auth_token + host_token
    if resolved_port is not None:
        netloc += f":{resolved_port}"

    return urlunsplit((split.scheme, netloc, split.path, split.query, split.fragment))
