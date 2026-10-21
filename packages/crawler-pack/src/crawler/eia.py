# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
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


log = logging.getLogger("eia")
log.setLevel(logging.INFO)

API_BASE_URL = "https://api.eia.gov/v2"
DOCS_URL = "https://www.eia.gov/opendata/documentation.php"

DEFAULT_REQUESTS = [
    {
        "id": "rto_fuel_type_california",
        "route": "electricity/rto/fuel-type-data/data/",
        "params": {
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": "CAL",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        },
    }
]


class EiaCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))
        self.request_pause_seconds = float(self.config.get("request_pause_seconds", 0.2))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS api_rows (
                        request_id text NOT NULL,
                        row_number integer NOT NULL,
                        period timestamp with time zone,
                        fetched_at timestamp with time zone NOT NULL,
                        payload_json text NOT NULL,
                        record_key text NOT NULL,
                        PRIMARY KEY (request_id, row_number, fetched_at)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS numeric_values (
                        request_id text NOT NULL,
                        period timestamp with time zone,
                        dimension text,
                        measure text NOT NULL,
                        value double precision,
                        unit text,
                        fetched_at timestamp with time zone NOT NULL,
                        record_key text NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eia_values_period ON numeric_values (period DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_eia_values_measure ON numeric_values (request_id, measure)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_values AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY request_id, dimension, measure
                                ORDER BY period DESC NULLS LAST, fetched_at DESC
                            ) AS rn
                        FROM numeric_values
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
                    CREATE OR REPLACE VIEW request_summary AS
                    SELECT
                        request_id,
                        measure,
                        count(*) AS values,
                        min(period) AS temporal_start,
                        max(period) AS temporal_end,
                        max(fetched_at) AS last_fetch
                    FROM numeric_values
                    GROUP BY request_id, measure
                    """
                )
            )

    def _api_key(self) -> str | None:
        api_key = config_or_env(self.config, "api_key", "EIA_API_KEY")
        return str(api_key) if has_credential(api_key) else None

    def _date_window(self) -> tuple[str, str]:
        now = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        lookback_days = int(self.config.get("lookback_days", 14))
        start = now - timedelta(days=lookback_days)
        return start.strftime("%Y-%m-%dT%H"), now.strftime("%Y-%m-%dT%H")

    def _request_params(self, request: dict[str, Any], api_key: str, offset: int, length: int) -> dict[str, Any]:
        params = dict(request.get("params", {}))
        params["api_key"] = api_key
        params["offset"] = offset
        params["length"] = length
        if request.get("use_default_date_window", True) and "start" not in params and "end" not in params:
            start, end = self._date_window()
            params["start"] = start
            params["end"] = end
        return params

    def _fetch_request(self, request: dict[str, Any], api_key: str) -> list[dict[str, Any]]:
        route = str(request["route"]).strip("/")
        length = int(request.get("page_size", self.config.get("page_size", 5000)))
        max_rows = int(request.get("max_rows", self.config.get("max_rows_per_request", 25000)))
        offset = 0
        rows = []
        while offset < max_rows:
            response = self.session.get(
                f"{API_BASE_URL}/{route}/",
                params=self._request_params(request, api_key, offset, length),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("response", {}).get("data", [])
            rows.extend(data)
            if len(data) < length:
                break
            offset += length
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
        return rows[:max_rows]

    def _parse_period(self, value: Any) -> datetime | None:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()

    def _normalize(self, request_id: str, rows: list[dict[str, Any]], fetched_at: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw_rows = []
        value_rows = []
        for row_number, row in enumerate(rows, start=1):
            period = self._parse_period(row.get("period"))
            raw_rows.append(
                {
                    "request_id": request_id,
                    "row_number": row_number,
                    "period": period,
                    "fetched_at": fetched_at,
                    "payload_json": compact_json(row),
                    "record_key": stable_hash(request_id, row_number, row),
                }
            )
            dimensions = []
            units = row.get("unit") or row.get("units")
            for key, value in row.items():
                normalized_key = normalize_column_name(key)
                if normalized_key in {"period", "unit", "units"}:
                    continue
                number = parse_number(value)
                if number is None and value not in (None, ""):
                    dimensions.append(f"{key}={value}")
            dimension = "; ".join(dimensions) if dimensions else None
            for key, value in row.items():
                normalized_key = normalize_column_name(key)
                if normalized_key in {"period", "unit", "units"}:
                    continue
                number = parse_number(value)
                if number is None:
                    continue
                value_rows.append(
                    {
                        "request_id": request_id,
                        "period": period,
                        "dimension": dimension,
                        "measure": key,
                        "value": number,
                        "unit": units,
                        "fetched_at": fetched_at,
                        "record_key": stable_hash(request_id, row_number, key, value),
                    }
                )
        return pd.DataFrame(raw_rows), pd.DataFrame(value_rows)

    def _replace_request(self, request_id: str, raw_rows: pd.DataFrame, value_rows: pd.DataFrame) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM api_rows WHERE request_id = :request_id"), {"request_id": request_id})
            conn.execute(text("DELETE FROM numeric_values WHERE request_id = :request_id"), {"request_id": request_id})
            if not raw_rows.empty:
                raw_rows.to_sql("api_rows", conn, if_exists="append", index=False)
            if not value_rows.empty:
                value_rows.to_sql("numeric_values", conn, if_exists="append", index=False)

    def run(self):
        self._prepare_schema()
        api_key = self._api_key()
        if not api_key:
            write_access_status(
                self.engine,
                source_name="U.S. EIA Open Data API",
                status="missing_credentials",
                access_model="Free EIA API key; DEMO_KEY is only suitable for limited testing",
                credentials_required=True,
                configured_credentials=False,
                message="Set EIA_API_KEY in crawler/.env for production access.",
                docs_url=DOCS_URL,
            )
            raise CrawlerSkipped("EIA API key missing; wrote access status only.")

        write_access_status(
            self.engine,
            source_name="U.S. EIA Open Data API",
            status="configured",
            access_model="API key query parameter",
            credentials_required=True,
            configured_credentials=True,
            message="EIA API key is configured.",
            docs_url=DOCS_URL,
        )
        requests_config = self.config.get("requests", DEFAULT_REQUESTS)
        total_rows = 0
        temporal_start = None
        temporal_end = None
        for request in requests_config:
            request_id = str(request["id"])
            rows = self._fetch_request(request, api_key)
            fetched_at = utc_now()
            raw_rows, value_rows = self._normalize(request_id, rows, fetched_at)
            self._replace_request(request_id, raw_rows, value_rows)
            total_rows += len(rows)
            if not value_rows.empty:
                current_start = value_rows["period"].min()
                current_end = value_rows["period"].max()
                temporal_start = current_start if temporal_start is None or current_start < temporal_start else temporal_start
                temporal_end = current_end if temporal_end is None or current_end > temporal_end else temporal_end
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": API_BASE_URL,
                "license": "EIA open data terms; cite EIA as source",
                "description": "Configured U.S. EIA Open Data API requests normalized into generic numeric value tables.",
                "contact": "https://www.eia.gov/about/contact/",
                "temporal_start": temporal_start.isoformat() if temporal_start is not None else None,
                "temporal_end": temporal_end.isoformat() if temporal_end is not None else None,
            }
        )
        self.logger.info("EIA crawler wrote %s API rows.", total_rows)


def main(schema_name: str = "eia"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    EiaCrawler("eia", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
