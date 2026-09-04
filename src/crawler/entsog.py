#!/usr/bin/env python3
# SPDX-FileCopyrightText: Florian Maurer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import text
from urllib3.util.retry import Retry

from crawler.common.base_crawler import BaseCrawler
from crawler.common.local_env import load_crawler_dotenv


API_ENDPOINT = "https://transparency.entsog.eu/api/v1/"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_CHUNK_DAYS = 7
DEFAULT_REQUEST_PAUSE_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 90

REFERENCE_ENDPOINTS = (
    ("operators", "operators", "operators"),
    ("connectionPoints", "connectionPoints", "connectionpoints"),
    ("balancingZones", "balancingZones", "balancingzones"),
    ("operatorPointDirections", "operatorPointDirections", "operatorpointdirections"),
    ("interconnections", "interconnections", "interconnections"),
    ("aggregateInterconnections", "aggregateInterconnections", "aggregateinterconnections"),
)

OPERATIONAL_INDICATORS = {
    "Physical Flow": "physical_flow",
    "Allocation": "allocation",
    "Firm Technical": "firm_technical",
}

log = logging.getLogger("entsog")
log.setLevel(logging.INFO)

metadata_info = {
    "schema_name": "entsog",
    "data_date": date.today().isoformat(),
    "data_source": API_ENDPOINT,
    "license": "https://www.entsog.eu/privacy-policy-and-terms-use",
    "description": "ENTSOG transparency platform reference and operational gas flow data.",
    "contact": "",
}


class EntsogCrawler(BaseCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.schema_name = self.get("schema_name")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=2.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _request_pause_seconds(self) -> float:
        return float(self.config.get("request_pause_seconds", DEFAULT_REQUEST_PAUSE_SECONDS))

    def _chunk_days(self) -> int:
        return int(self.config.get("chunk_days", DEFAULT_CHUNK_DAYS))

    def _initial_start_date(self) -> date:
        configured = str(self.config.get("default_start_date", DEFAULT_START_DATE)).strip()
        return pd.Timestamp(configured).date()

    def _fetch_collection(self, endpoint: str, root_key: str, params: dict | None = None) -> pd.DataFrame:
        query_params = {
            "periodize": "false",
            "includeExemptions": "true",
        }
        if params:
            query_params.update({key: value for key, value in params.items() if value is not None})

        response = self.session.get(
            f"{API_ENDPOINT}{endpoint}",
            params=query_params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        rows = payload.get(root_key)
        if rows is None:
            data_keys = [key for key in payload if key != "meta"]
            rows = payload.get(data_keys[0], []) if data_keys else []
        if not rows:
            return pd.DataFrame()

        frame = pd.DataFrame(rows).replace([""], [None])
        frame.columns = [column.lower() for column in frame.columns]
        return frame

    def _write_reference_table(self, endpoint: str, root_key: str, table_name: str) -> None:
        frame = self._fetch_collection(endpoint, root_key)
        if frame.empty:
            self.logger.warning("ENTSOG reference endpoint %s returned no rows", endpoint)
            return

        with self.engine.begin() as conn:
            frame.to_sql(table_name, conn, schema=self.schema_name, if_exists="replace", index=False)
        self.logger.info("ENTSOG reference table %s refreshed with %s rows", table_name, len(frame))

    def _existing_start_date(self, table_name: str) -> date:
        fallback = self._initial_start_date()
        query = text(
            f'SELECT max(periodfrom) FROM "{self.schema_name}"."{table_name}"'
        )
        try:
            with self.engine.begin() as conn:
                max_periodfrom = conn.execute(query).scalar_one_or_none()
        except Exception:
            return fallback

        if max_periodfrom is None:
            return fallback

        latest = pd.Timestamp(max_periodfrom).date() - timedelta(days=1)
        return latest if latest > fallback else fallback

    def _delete_chunk(self, table_name: str, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp) -> None:
        delete_query = text(
            f'''
            DELETE FROM "{self.schema_name}"."{table_name}"
            WHERE periodfrom >= :chunk_start
              AND periodfrom < :chunk_end
            '''
        )
        with self.engine.begin() as conn:
            conn.execute(delete_query, {"chunk_start": chunk_start, "chunk_end": chunk_end})

    def _write_operational_chunk(self, table_name: str, frame: pd.DataFrame, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp) -> None:
        if frame.empty:
            return

        frame["periodfrom"] = pd.to_datetime(frame["periodfrom"], utc=True, errors="coerce")
        frame["periodto"] = pd.to_datetime(frame["periodto"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["periodfrom", "periodto"]).copy()
        if frame.empty:
            return

        if table_name == "firm_technical":
            frame["index"] = pd.to_numeric(frame.get("value"), errors="coerce")

        try:
            self._delete_chunk(table_name, chunk_start, chunk_end)
        except Exception:
            pass

        with self.engine.begin() as conn:
            frame.to_sql(table_name, conn, schema=self.schema_name, if_exists="append", index=False)

    def _refresh_indicator(self, indicator: str, table_name: str) -> None:
        chunk_days = self._chunk_days()
        pause_seconds = self._request_pause_seconds()
        start_day = self._existing_start_date(table_name)
        end_day = pd.Timestamp.utcnow().date() + timedelta(days=1)

        if start_day >= end_day:
            self.logger.info("ENTSOG %s already up to date", table_name)
            return

        current = start_day
        while current < end_day:
            next_day = min(current + timedelta(days=chunk_days), end_day)
            params = {
                "limit": -1,
                "indicator": indicator,
                "from": current.isoformat(),
                "to": next_day.isoformat(),
                "periodType": "hour",
            }
            self.logger.info(
                "ENTSOG %s: fetching %s to %s",
                table_name,
                current.isoformat(),
                next_day.isoformat(),
            )
            frame = self._fetch_collection("operationaldatas", "operationaldatas", params)
            self._write_operational_chunk(
                table_name,
                frame,
                pd.Timestamp(current, tz="UTC"),
                pd.Timestamp(next_day, tz="UTC"),
            )
            current = next_day
            if current < end_day and pause_seconds > 0:
                time.sleep(pause_seconds)

    def _ensure_indexes(self) -> None:
        statements = (
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_physical_flow_periodfrom" ON "{self.schema_name}"."physical_flow" (periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_physical_flow_operator" ON "{self.schema_name}"."physical_flow" (operatorkey, periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_physical_flow_point" ON "{self.schema_name}"."physical_flow" (pointlabel, periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_allocation_periodfrom" ON "{self.schema_name}"."allocation" (periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_allocation_operator" ON "{self.schema_name}"."allocation" (operatorkey, periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_allocation_point" ON "{self.schema_name}"."allocation" (pointlabel, periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_firm_technical_periodfrom" ON "{self.schema_name}"."firm_technical" (periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_firm_technical_operator" ON "{self.schema_name}"."firm_technical" (operatorkey, periodfrom)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsog_opd_operator" ON "{self.schema_name}"."operatorpointdirections" (operatorkey, pointlabel)',
        )
        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

    def run(self):
        for endpoint, root_key, table_name in REFERENCE_ENDPOINTS:
            self._write_reference_table(endpoint, root_key, table_name)

        for indicator, table_name in OPERATIONAL_INDICATORS.items():
            self._refresh_indicator(indicator, table_name)

        self._ensure_indexes()

        metadata = dict(metadata_info)
        metadata["temporal_start"] = str(self._initial_start_date())
        metadata["temporal_end"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.set_metadata(metadata)


def main(schema_name: str):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
        "default_start_date": DEFAULT_START_DATE,
        "chunk_days": DEFAULT_CHUNK_DAYS,
    }
    crawler = EntsogCrawler("entsog", config)
    crawler.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main("entsog")
