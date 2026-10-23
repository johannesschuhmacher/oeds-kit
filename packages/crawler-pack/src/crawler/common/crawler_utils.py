# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import text
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = "OEDS crawler/0.1 (+https://open-energy-data-server.readthedocs.io/)"


def copy_insert(pd_table, conn, keys, data_iter) -> None:
    """``DataFrame.to_sql(method=copy_insert)``: write rows with PostgreSQL COPY.

    About ten times faster than pandas' default executemany for large frames
    (300k MaStR rows: 6 s instead of 69 s). Other databases use a plain insert.
    """
    if conn.dialect.name != "postgresql":
        conn.execute(pd_table.table.insert(), [dict(zip(keys, row)) for row in data_iter])
        return
    # pandas stores an integer column with gaps as float. INSERT casts 0.0 into a
    # bigint column, COPY rejects "0.0" (ENTSOG idpointtype), so whole floats are
    # written as integers; a double precision column reads them unchanged.
    rows = ([int(v) if isinstance(v, float) and v.is_integer() else v for v in row] for row in data_iter)
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    buffer.seek(0)
    target = f'"{pd_table.schema}"."{pd_table.name}"' if pd_table.schema else f'"{pd_table.name}"'
    columns = ", ".join(f'"{key}"' for key in keys)
    with conn.connection.cursor() as cursor:
        cursor.copy_expert(f"COPY {target} ({columns}) FROM STDIN WITH (FORMAT csv)", buffer)


def build_session(user_agent: str | None = None, retries: int = 4, backoff_factor: float = 1.0) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent or DEFAULT_USER_AGENT})
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def config_or_env(config: dict[str, Any], config_key: str, env_key: str, default: Any = None) -> Any:
    value = config.get(config_key)
    if value not in (None, ""):
        return value
    return os.getenv(env_key, default)


def has_credential(value: Any) -> bool:
    return value not in (None, "", "your_token", "your_client_id", "your_client_secret")


class CrawlerSkipped(Exception):
    """Raised when a run has nothing to do, for example because credentials are missing.

    The scheduler reports such runs as "skipped" instead of "succeeded" or "failed".
    """


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def stable_hash(*parts: Any) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_column_name(column: Any) -> str:
    normalized = str(column).strip().lower()
    normalized = (
        normalized.replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00df", "ss")
        .replace("\u00c3\u00a4", "ae")
        .replace("\u00c3\u00b6", "oe")
        .replace("\u00c3\u00bc", "ue")
        .replace("\u00c3\u009f", "ss")
    )
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_") or "value"


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"nan", "none", "null", "-"}:
        return None
    text_value = text_value.replace("\u00a0", "").replace(" ", "")
    if "," in text_value and "." in text_value:
        text_value = text_value.replace(".", "").replace(",", ".")
    elif "," in text_value:
        text_value = text_value.replace(",", ".")
    try:
        return float(text_value)
    except ValueError:
        return None


def json_ready(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def compact_json(data: Any) -> str:
    return json.dumps(json_ready(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ensure_access_status_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS access_status (
                    source_name text PRIMARY KEY,
                    status text NOT NULL,
                    access_model text,
                    credentials_required boolean NOT NULL DEFAULT false,
                    configured_credentials boolean NOT NULL DEFAULT false,
                    message text,
                    docs_url text,
                    checked_at timestamp with time zone NOT NULL
                )
                """
            )
        )


def write_access_status(
    engine,
    *,
    source_name: str,
    status: str,
    access_model: str,
    credentials_required: bool,
    configured_credentials: bool,
    message: str,
    docs_url: str,
) -> None:
    ensure_access_status_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO access_status
                    (source_name, status, access_model, credentials_required, configured_credentials, message, docs_url, checked_at)
                VALUES
                    (:source_name, :status, :access_model, :credentials_required, :configured_credentials, :message, :docs_url, :checked_at)
                ON CONFLICT (source_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    access_model = EXCLUDED.access_model,
                    credentials_required = EXCLUDED.credentials_required,
                    configured_credentials = EXCLUDED.configured_credentials,
                    message = EXCLUDED.message,
                    docs_url = EXCLUDED.docs_url,
                    checked_at = EXCLUDED.checked_at
                """
            ),
            {
                "source_name": source_name,
                "status": status,
                "access_model": access_model,
                "credentials_required": credentials_required,
                "configured_credentials": configured_credentials,
                "message": message,
                "docs_url": docs_url,
                "checked_at": utc_now(),
            },
        )
