# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
import re
import time
from typing import Any

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import (
    CrawlerSkipped,
    build_session,
    compact_json,
    config_or_env,
    has_credential,
    normalize_column_name,
    parse_number,
    stable_hash,
    utc_now,
    write_access_status,
)
from crawler.common.local_env import load_crawler_dotenv


log = logging.getLogger("netztransparenz")
log.setLevel(logging.INFO)

BASE_DATA_URL = "https://ds.netztransparenz.de/api/v1/data"
HEALTH_URL = "https://ds.netztransparenz.de/api/v1/health"
TOKEN_URL = "https://identity.netztransparenz.de/users/connect/token"
DOCS_URL = "https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/web-api/dokumentation-webserviceapi-netztransparenz_v1.21.pdf"

DEFAULT_ENDPOINTS = [
    {
        "id": "nrv_saldo_minute",
        "label": "NRV-Saldo minutely operational",
        "path": "NrvSaldo/nrvSaldoMinute/Betrieblich",
        "format": "csv",
    },
    {
        "id": "nrv_saldo_operational",
        "label": "NRV-Saldo operational",
        "path": "NrvSaldo/NRVSaldo/Betrieblich",
        "format": "csv",
    },
    {
        "id": "rebap_quality_assured",
        "label": "reBAP quality assured",
        "path": "NrvSaldo/reBAP/Qualitaetsgesichert",
        "format": "csv",
    },
    {
        "id": "mFRR_satisfied_demand",
        "label": "mFRR satisfied demand operational",
        "path": "NrvSaldo/mFRRSatisfiedDemand/Betrieblich",
        "format": "csv",
    },
    {
        "id": "online_solar_actuals",
        "label": "Online solar actuals",
        "path": "onlinehochrechnung/Solar",
        "format": "csv",
    },
    {
        "id": "online_wind_onshore_actuals",
        "label": "Online wind onshore actuals",
        "path": "onlinehochrechnung/Windonshore",
        "format": "csv",
    },
    {
        "id": "spot_market_prices",
        "label": "Spot market prices",
        "path": "Spotmarktpreise",
        "format": "csv",
    },
]

METADATA_COLUMN_KEYS = {
    "datum",
    "von",
    "bis",
    "zeitzone",
    "zeitzone_von",
    "zeitzone_bis",
    "datenkategorie",
    "datentyp",
    "einheit",
    "status",
    "anspruchverguetung",
    "mol_abweichung",
}


class NetztransparenzCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 60))
        self.request_pause_seconds = float(self.config.get("request_pause_seconds", 0.6))

    def _client_credentials(self) -> tuple[str | None, str | None]:
        client_id = config_or_env(self.config, "client_id", "NETZTRANSPARENZ_CLIENT_ID")
        client_secret = config_or_env(self.config, "client_secret", "NETZTRANSPARENZ_CLIENT_SECRET")
        return client_id, client_secret

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS endpoint_runs (
                        endpoint_id text NOT NULL,
                        label text,
                        requested_from timestamp with time zone,
                        requested_to timestamp with time zone,
                        fetched_at timestamp with time zone NOT NULL,
                        status_code integer,
                        row_count integer NOT NULL DEFAULT 0,
                        source_url text,
                        error text,
                        PRIMARY KEY (endpoint_id, fetched_at)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS raw_rows (
                        endpoint_id text NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        row_number integer NOT NULL,
                        record_key text NOT NULL,
                        payload_json text NOT NULL,
                        PRIMARY KEY (endpoint_id, fetched_at, row_number)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS normalized_values (
                        endpoint_id text NOT NULL,
                        label text,
                        timestamp_from timestamp with time zone,
                        timestamp_to timestamp with time zone,
                        category text,
                        data_type text,
                        unit text,
                        area text NOT NULL,
                        direction text,
                        value double precision,
                        status text,
                        fetched_at timestamp with time zone NOT NULL,
                        record_key text NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ntz_norm_time ON normalized_values (timestamp_from DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ntz_norm_endpoint_area ON normalized_values (endpoint_id, area)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_values AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY endpoint_id, area, direction
                                ORDER BY timestamp_from DESC NULLS LAST, fetched_at DESC
                            ) AS rn
                        FROM normalized_values
                        WHERE value IS NOT NULL
                    )
                    SELECT *
                    FROM ranked
                    WHERE rn = 1
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW endpoint_summary AS
                    SELECT
                        endpoint_id,
                        label,
                        count(*) AS value_rows,
                        min(timestamp_from) AS temporal_start,
                        max(timestamp_from) AS temporal_end,
                        max(fetched_at) AS last_fetch
                    FROM normalized_values
                    GROUP BY endpoint_id, label
                    """
                )
            )

    def _write_run(
        self,
        endpoint: dict[str, Any],
        fetched_at: datetime,
        date_from: datetime | None,
        date_to: datetime | None,
        status_code: int | None,
        row_count: int,
        source_url: str,
        error: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO endpoint_runs
                        (endpoint_id, label, requested_from, requested_to, fetched_at, status_code, row_count, source_url, error)
                    VALUES
                        (:endpoint_id, :label, :requested_from, :requested_to, :fetched_at, :status_code, :row_count, :source_url, :error)
                    ON CONFLICT (endpoint_id, fetched_at) DO UPDATE SET
                        row_count = EXCLUDED.row_count,
                        status_code = EXCLUDED.status_code,
                        source_url = EXCLUDED.source_url,
                        error = EXCLUDED.error
                    """
                ),
                {
                    "endpoint_id": endpoint["id"],
                    "label": endpoint.get("label", endpoint["id"]),
                    "requested_from": date_from,
                    "requested_to": date_to,
                    "fetched_at": fetched_at,
                    "status_code": status_code,
                    "row_count": row_count,
                    "source_url": source_url,
                    "error": error,
                },
            )

    def _access_token(self) -> str | None:
        client_id, client_secret = self._client_credentials()
        configured = has_credential(client_id) and has_credential(client_secret)
        if not configured:
            write_access_status(
                self.engine,
                source_name="Netztransparenz WebAPI",
                status="missing_credentials",
                access_model="OAuth2 client_credentials; free registration in the Netztransparenz WebAPI portal",
                credentials_required=True,
                configured_credentials=False,
                message="Set NETZTRANSPARENZ_CLIENT_ID and NETZTRANSPARENZ_CLIENT_SECRET in crawler/.env.",
                docs_url=DOCS_URL,
            )
            return None

        response = self.session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("Netztransparenz token response did not contain access_token.")
        write_access_status(
            self.engine,
            source_name="Netztransparenz WebAPI",
            status="configured",
            access_model="OAuth2 client_credentials",
            credentials_required=True,
            configured_credentials=True,
            message="Client credentials are configured and token retrieval succeeded.",
            docs_url=DOCS_URL,
        )
        return token

    def _date_window(self) -> tuple[datetime, datetime]:
        now = utc_now().replace(second=0, microsecond=0)
        lookback_days = int(self.config.get("lookback_days", 7))
        default_start = self.config.get("default_start_date")
        if default_start:
            start = pd.Timestamp(default_start, tz="UTC").to_pydatetime()
            if (now - start).days > lookback_days:
                start = now - timedelta(days=lookback_days)
        else:
            start = now - timedelta(days=lookback_days)
        return start, now

    def _endpoint_url(self, endpoint: dict[str, Any], date_from: datetime, date_to: datetime) -> str:
        path = endpoint["path"].strip("/")
        url = f"{BASE_DATA_URL}/{path}"
        if endpoint.get("use_date_path", True):
            url += f"/{date_from.strftime('%Y-%m-%dT%H:%M:%S')}/{date_to.strftime('%Y-%m-%dT%H:%M:%S')}"
        return url

    def _parse_timestamp(self, row: pd.Series, date_column: str, time_column: str | None) -> pd.Timestamp | None:
        date_value = row.get(date_column)
        if pd.isna(date_value) or str(date_value).strip() == "":
            return None
        if time_column:
            value = f"{date_value} {row.get(time_column, '')}".strip()
        else:
            value = str(date_value).strip()
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        timezone_column = None
        for candidate in ("Zeitzone", "Zeitzone von"):
            if candidate in row.index:
                timezone_column = candidate
                break
        timezone_value = str(row.get(timezone_column, "UTC")).strip().upper() if timezone_column else "UTC"
        if parsed.tzinfo is None:
            if timezone_value == "UTC":
                parsed = parsed.tz_localize("UTC")
            else:
                parsed = parsed.tz_localize("Europe/Berlin", ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")
        else:
            parsed = parsed.tz_convert("UTC")
        return parsed

    def _area_and_direction(self, column_name: str) -> tuple[str, str | None]:
        direction = None
        lowered = column_name.lower()
        if "positiv" in lowered:
            direction = "positive"
        elif "negativ" in lowered:
            direction = "negative"
        area = re.sub(r"\s*\((?:mw|mwh|eur/mwh|positiv|negativ|status).*?\)", "", column_name, flags=re.IGNORECASE)
        return area.strip() or column_name, direction

    def _normalize_csv(self, endpoint: dict[str, Any], frame: pd.DataFrame, fetched_at: datetime) -> pd.DataFrame:
        rows = []
        date_column = next((column for column in frame.columns if normalize_column_name(column) == "datum"), None)
        from_column = next((column for column in frame.columns if normalize_column_name(column) == "von"), None)
        to_column = next((column for column in frame.columns if normalize_column_name(column) == "bis"), None)
        for _, row in frame.iterrows():
            timestamp_from = self._parse_timestamp(row, date_column, from_column) if date_column else None
            timestamp_to = self._parse_timestamp(row, date_column, to_column) if date_column and to_column else None
            category = row.get("Datenkategorie")
            data_type = row.get("Datentyp")
            unit = row.get("Einheit")
            status = row.get("Status")
            for column in frame.columns:
                normalized_column = normalize_column_name(column)
                if normalized_column in METADATA_COLUMN_KEYS:
                    continue
                value = parse_number(row.get(column))
                if value is None:
                    continue
                area, direction = self._area_and_direction(str(column))
                record_key = stable_hash(endpoint["id"], timestamp_from, area, direction, category, data_type, value)
                rows.append(
                    {
                        "endpoint_id": endpoint["id"],
                        "label": endpoint.get("label", endpoint["id"]),
                        "timestamp_from": timestamp_from.to_pydatetime() if timestamp_from is not None else None,
                        "timestamp_to": timestamp_to.to_pydatetime() if timestamp_to is not None else None,
                        "category": category,
                        "data_type": data_type,
                        "unit": unit,
                        "area": area,
                        "direction": direction,
                        "value": value,
                        "status": status,
                        "fetched_at": fetched_at,
                        "record_key": record_key,
                    }
                )
        return pd.DataFrame(rows)

    def _write_raw_rows(self, endpoint_id: str, fetched_at: datetime, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        rows = [
            {
                "endpoint_id": endpoint_id,
                "fetched_at": fetched_at,
                "row_number": index,
                "record_key": stable_hash(endpoint_id, index, record),
                "payload_json": compact_json(record),
            }
            for index, record in enumerate(records, start=1)
        ]
        with self.engine.begin() as conn:
            pd.DataFrame(rows).to_sql("raw_rows", conn, if_exists="append", index=False)

    def _replace_normalized_window(self, endpoint_id: str, frame: pd.DataFrame, date_from: datetime, date_to: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    DELETE FROM normalized_values
                    WHERE endpoint_id = :endpoint_id
                      AND (timestamp_from IS NULL OR (timestamp_from >= :date_from AND timestamp_from <= :date_to))
                    """
                ),
                {"endpoint_id": endpoint_id, "date_from": date_from, "date_to": date_to},
            )
            if not frame.empty:
                frame.to_sql("normalized_values", conn, if_exists="append", index=False)

    def _fetch_endpoint(self, endpoint: dict[str, Any], token: str, date_from: datetime, date_to: datetime) -> int:
        fetched_at = utc_now()
        url = self._endpoint_url(endpoint, date_from, date_to)
        response = self.session.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json,text/csv,*/*"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        row_count = 0
        if endpoint.get("format") == "json":
            payload = response.json()
            records = payload if isinstance(payload, list) else [payload]
            self._write_raw_rows(endpoint["id"], fetched_at, records)
            row_count = len(records)
        else:
            frame = pd.read_csv(io.StringIO(response.text), sep=";", dtype=str)
            frame = frame.dropna(how="all")
            records = frame.where(pd.notnull(frame), None).to_dict(orient="records")
            self._write_raw_rows(endpoint["id"], fetched_at, records)
            normalized = self._normalize_csv(endpoint, frame, fetched_at)
            self._replace_normalized_window(endpoint["id"], normalized, date_from, date_to)
            row_count = len(frame)

        self._write_run(endpoint, fetched_at, date_from, date_to, response.status_code, row_count, url)
        return row_count

    def run(self):
        self._prepare_schema()
        failures: list[str] = []
        token = self._access_token()
        if not token:
            raise CrawlerSkipped("Netztransparenz credentials are missing; wrote access status only.")

        health = self.session.get(HEALTH_URL, timeout=self.timeout_seconds)
        health.raise_for_status()

        date_from, date_to = self._date_window()
        endpoints = self.config.get("endpoints", DEFAULT_ENDPOINTS)
        total_rows = 0
        for endpoint in endpoints:
            try:
                total_rows += self._fetch_endpoint(endpoint, token, date_from, date_to)
            except Exception as exc:
                self.logger.error("Netztransparenz endpoint %s failed: %s", endpoint.get("id"), exc)
                failures.append(str(endpoint.get("id")))
                self._write_run(endpoint, utc_now(), date_from, date_to, None, 0, self._endpoint_url(endpoint, date_from, date_to), str(exc))
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": BASE_DATA_URL,
                "license": "Netztransparenz WebAPI terms; review upstream terms before republication",
                "description": "Netztransparenz WebAPI energy balancing, EEG/KWKG and market transparency datasets.",
                "contact": "https://www.netztransparenz.de/",
                "temporal_start": date_from.isoformat(),
                "temporal_end": date_to.isoformat(),
            }
        )
        self.logger.info("Netztransparenz crawler finished with %s raw rows.", total_rows)
        if failures:
            raise RuntimeError(f"Netztransparenz endpoints failed: {', '.join(failures)}")


def main(schema_name: str = "netztransparenz"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    NetztransparenzCrawler("netztransparenz", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
