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
    parse_number,
    stable_hash,
    utc_now,
    write_access_status,
)
from crawler.common.local_env import load_crawler_dotenv


log = logging.getLogger("gie_agsi_alsi")
log.setLevel(logging.INFO)

DOCS_URL = "https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf"
PLATFORMS = {
    "agsi": "https://agsi.gie.eu/api",
    "alsi": "https://alsi.gie.eu/api",
}

DEFAULT_QUERIES = [
    {"platform": "agsi", "scope": "EU", "params": {"type": "eu"}},
    {"platform": "agsi", "scope": "DE", "params": {"country": "DE"}},
    {"platform": "alsi", "scope": "EU", "params": {"type": "eu"}},
    {"platform": "alsi", "scope": "DE", "params": {"country": "DE"}},
]


class GieAgsiAlsiCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))
        self.request_pause_seconds = float(self.config.get("request_pause_seconds", 0.4))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS daily_inventory (
                        platform text NOT NULL,
                        scope text NOT NULL,
                        name text,
                        code text,
                        url text,
                        gas_day_start date NOT NULL,
                        gas_in_storage double precision,
                        consumption double precision,
                        consumption_full double precision,
                        injection double precision,
                        withdrawal double precision,
                        working_gas_volume double precision,
                        injection_capacity double precision,
                        withdrawal_capacity double precision,
                        full_pct double precision,
                        status text,
                        trend text,
                        fetched_at timestamp with time zone NOT NULL,
                        payload_json text NOT NULL,
                        record_key text NOT NULL,
                        PRIMARY KEY (platform, scope, code, gas_day_start)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gie_inventory_day ON daily_inventory (gas_day_start DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_gie_inventory_platform ON daily_inventory (platform, scope)"))
            conn.execute(text("""
                ALTER TABLE daily_inventory
                    ADD COLUMN IF NOT EXISTS lng_inventory_gwh double precision,
                    ADD COLUMN IF NOT EXISTS lng_inventory_thousand_m3 double precision,
                    ADD COLUMN IF NOT EXISTS lng_storage_capacity_gwh double precision,
                    ADD COLUMN IF NOT EXISTS lng_storage_capacity_thousand_m3 double precision,
                    ADD COLUMN IF NOT EXISTS lng_send_out_gwh_per_day double precision,
                    ADD COLUMN IF NOT EXISTS lng_send_out_capacity_gwh_per_day double precision
            """))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_inventory AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY platform, scope, code
                                ORDER BY gas_day_start DESC, fetched_at DESC
                            ) AS rn
                        FROM daily_inventory
                    )
                    SELECT platform, scope, name, code, url, gas_day_start,
                        gas_in_storage, consumption, consumption_full, injection,
                        withdrawal, working_gas_volume, injection_capacity,
                        withdrawal_capacity, full_pct, status, trend, fetched_at,
                        payload_json, record_key, rn,
                        lng_inventory_gwh, lng_inventory_thousand_m3,
                        lng_storage_capacity_gwh, lng_storage_capacity_thousand_m3,
                        lng_send_out_gwh_per_day, lng_send_out_capacity_gwh_per_day
                    FROM ranked
                    WHERE rn = 1
                    """
                )
            )

    def _api_key(self) -> str | None:
        api_key = config_or_env(self.config, "api_key", "GIE_API_KEY")
        if not has_credential(api_key):
            write_access_status(
                self.engine,
                source_name="GIE AGSI/ALSI",
                status="missing_credentials",
                access_model="Free AGSI/ALSI account with API key passed as x-key header",
                credentials_required=True,
                configured_credentials=False,
                message="Set GIE_API_KEY in crawler/.env. GIE says AGSI and ALSI API accounts can be set up free of charge.",
                docs_url=DOCS_URL,
            )
            return None
        write_access_status(
            self.engine,
            source_name="GIE AGSI/ALSI",
            status="configured",
            access_model="x-key API key",
            credentials_required=True,
            configured_credentials=True,
            message="GIE API key is configured.",
            docs_url=DOCS_URL,
        )
        return str(api_key)

    def _date_window(self) -> tuple[str, str]:
        today = datetime.now(tz=timezone.utc).date()
        lookback_days = int(self.config.get("lookback_days", 30))
        return (today - timedelta(days=lookback_days)).isoformat(), today.isoformat()

    def _fetch_query(self, query: dict[str, Any], api_key: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
        platform = query["platform"]
        base_url = PLATFORMS[platform]
        params = dict(query.get("params", {}))
        params.update({"from": date_from, "to": date_to, "size": int(self.config.get("page_size", 300)), "page": 1})
        rows = []
        while True:
            response = self.session.get(base_url, params=params, headers={"x-key": api_key}, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("data", []))
            last_page = int(payload.get("last_page") or 1)
            if params["page"] >= last_page:
                break
            params["page"] += 1
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
        return rows

    def _normalize_rows(self, query: dict[str, Any], rows: list[dict[str, Any]], fetched_at: datetime) -> pd.DataFrame:
        normalized_rows = []
        for row in rows:
            gas_day = row.get("gasDayStart") or row.get("gas_day") or row.get("gasDay")
            parsed_day = pd.to_datetime(gas_day, errors="coerce")
            if pd.isna(parsed_day):
                continue
            code = row.get("code") or row.get("url") or row.get("name") or query.get("scope")
            # ALSI quantities have different units from AGSI; retain both source units.
            inventory = row.get("inventory") or {}
            capacity = row.get("dtmi") or {}
            if not isinstance(inventory, dict):
                inventory = {"lng": inventory}
            if not isinstance(capacity, dict):
                capacity = {"lng": capacity}
            normalized_rows.append(
                {
                    "platform": query["platform"],
                    "scope": query.get("scope", ""),
                    "name": row.get("name"),
                    "code": code,
                    "url": row.get("url"),
                    "gas_day_start": parsed_day.date(),
                    "gas_in_storage": parse_number(row.get("gasInStorage")),
                    "consumption": parse_number(row.get("consumption")),
                    "consumption_full": parse_number(row.get("consumptionFull")),
                    "injection": parse_number(row.get("injection")),
                    "withdrawal": parse_number(row.get("withdrawal")),
                    "working_gas_volume": parse_number(row.get("workingGasVolume")),
                    "injection_capacity": parse_number(row.get("injectionCapacity")),
                    "withdrawal_capacity": parse_number(row.get("withdrawalCapacity")),
                    "full_pct": parse_number(row.get("full")),
                    "lng_inventory_gwh": parse_number(inventory.get("gwh")),
                    "lng_inventory_thousand_m3": parse_number(inventory.get("lng")),
                    "lng_storage_capacity_gwh": parse_number(capacity.get("gwh")),
                    "lng_storage_capacity_thousand_m3": parse_number(capacity.get("lng")),
                    "lng_send_out_gwh_per_day": parse_number(row.get("sendOut")),
                    "lng_send_out_capacity_gwh_per_day": parse_number(row.get("dtrs")),
                    "status": row.get("status"),
                    "trend": row.get("trend"),
                    "fetched_at": fetched_at,
                    "payload_json": compact_json(row),
                    "record_key": stable_hash(query["platform"], query.get("scope"), code, gas_day, row),
                }
            )
        return pd.DataFrame(normalized_rows)

    def _replace_window(self, frame: pd.DataFrame, date_from: str, date_to: str) -> None:
        if frame.empty:
            return
        with self.engine.begin() as conn:
            for platform, scope in frame[["platform", "scope"]].drop_duplicates().itertuples(index=False):
                conn.execute(
                    text(
                        """
                        DELETE FROM daily_inventory
                        WHERE platform = :platform
                          AND scope = :scope
                          AND gas_day_start >= :date_from
                          AND gas_day_start <= :date_to
                        """
                    ),
                    {"platform": platform, "scope": scope, "date_from": date_from, "date_to": date_to},
                )
            frame.to_sql("daily_inventory", conn, if_exists="append", index=False)

    def run(self):
        self._prepare_schema()
        failures: list[str] = []
        api_key = self._api_key()
        if not api_key:
            raise CrawlerSkipped("GIE API key missing; wrote access status only.")

        date_from, date_to = self._date_window()
        fetched_at = utc_now()
        queries = self.config.get("queries", DEFAULT_QUERIES)
        frames = []
        for query in queries:
            try:
                rows = self._fetch_query(query, api_key, date_from, date_to)
                frames.append(self._normalize_rows(query, rows, fetched_at))
            except Exception as exc:
                self.logger.error("GIE query %s failed: %s", query, exc)
                failures.append(str(query))
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            self._replace_window(combined, date_from, date_to)
        else:
            combined = pd.DataFrame()

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": "https://agsi.gie.eu/api and https://alsi.gie.eu/api",
                "license": "GIE AGSI/ALSI transparency platform terms; review before republication",
                "description": "European gas storage and LNG transparency data via GIE AGSI/ALSI API.",
                "contact": "api@gie.eu",
                "temporal_start": date_from,
                "temporal_end": date_to,
            }
        )
        self.logger.info("GIE AGSI/ALSI crawler wrote %s rows.", len(combined))
        if failures:
            raise RuntimeError(f"GIE queries failed: {', '.join(failures)}")


def main(schema_name: str = "gie_agsi_alsi"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    GieAgsiAlsiCrawler("gie_agsi_alsi", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
