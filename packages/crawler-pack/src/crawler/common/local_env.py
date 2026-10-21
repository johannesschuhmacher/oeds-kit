# SPDX-FileCopyrightText: OEDS Contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import os
import re

from dotenv import load_dotenv

_LOADED_DOTENV_PATHS: set[Path] = set()


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_crawler_env_path(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    return root / "crawler" / ".env"


def load_crawler_dotenv(repo_root: Path | None = None) -> None:
    dotenv_path = get_crawler_env_path(repo_root)
    if dotenv_path in _LOADED_DOTENV_PATHS:
        return
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)
    _LOADED_DOTENV_PATHS.add(dotenv_path)


def apply_email_env_overrides(config: dict[str, Any] | None, repo_root: Path | None = None) -> dict[str, Any] | None:
    load_crawler_dotenv(repo_root)

    if config is None:
        return None
    if not isinstance(config, dict):
        return config

    toaddrs_raw = str(os.getenv("OEDS_EMAIL_TOADDRS", "")).strip()
    mailhost = str(os.getenv("OEDS_EMAIL_MAILHOST", "")).strip()
    fromaddr = str(os.getenv("OEDS_EMAIL_FROMADDR", "")).strip()
    subject = str(os.getenv("OEDS_EMAIL_SUBJECT", "")).strip()
    username = str(os.getenv("OEDS_EMAIL_USERNAME", "")).strip()
    password = str(os.getenv("OEDS_EMAIL_PASSWORD", "")).strip()

    if not any([toaddrs_raw, mailhost, fromaddr, subject, username, password]):
        return config

    updated = deepcopy(config)
    default_config = updated.setdefault("default", {})
    if not isinstance(default_config, dict):
        return updated

    email_config = default_config.setdefault("email", {})
    if not isinstance(email_config, dict):
        default_config["email"] = {}
        email_config = default_config["email"]

    if toaddrs_raw:
        parsed_toaddrs = [token.strip() for token in re.split(r"[,\n;]+", toaddrs_raw) if token.strip()]
        email_config["toaddrs"] = parsed_toaddrs
    if mailhost:
        email_config["mailhost"] = mailhost
    if fromaddr:
        email_config["fromaddr"] = fromaddr
    if subject:
        email_config["subject"] = subject
    if username:
        email_config["username"] = username
    if password:
        email_config["password"] = password

    return updated
