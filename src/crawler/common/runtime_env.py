# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path
import os
from urllib.parse import quote, urlsplit, urlunsplit

from crawler.common.local_env import get_repo_root, load_crawler_dotenv

__all__ = ["get_repo_root", "load_local_crawler_env", "resolve_database_uri"]


def load_local_crawler_env(repo_root: Path | None = None) -> None:
    """Alias kept for ``crawler_core.runtime_env``; use ``local_env.load_crawler_dotenv``."""
    load_crawler_dotenv(repo_root)


def resolve_database_uri(database_uri: str) -> str:
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
