# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import xml.etree.ElementTree as ET

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import (
    build_session,
    compact_json,
    normalize_column_name,
    parse_number,
    stable_hash,
    utc_now,
    write_access_status,
)


log = logging.getLogger("tradinghub")
log.setLevel(logging.INFO)

BASE_URL = "https://datenservice.tradinghub.eu/XmlInterface/getXML.ashx"
DOCS_URL = "https://www.tradinghub.eu/Portals/0/DLC%20Datenformate/2024/240101_THE_XML_Interface_V1.1_en.pdf?ver=B38fHTVUA-mqEK7BVy-dWA%3D%3D"

DEFAULT_REPORTS = [
    "PricesEnergyImbalance",
    "PricesEnergyImbalancePreliminary",
    "PricesFlexibilityCharge",
    "ExternalBalancingGas",
    "InternalBalancingGas",
    "BalancingGasContractedCapacity",
    "CommercialConversion",
    "TechnicalConversion",
    "AggregatedConsumptionData",
    "AggregateImbalancePositions",
    "MarketAreaMonitor",
]

DATE_COLUMNS = {"gasday", "date", "validfrom", "validto", "periodfrom", "periodto", "day"}
NON_VALUE_COLUMNS = DATE_COLUMNS | {"status", "unit", "gasquality", "balancinggasquality", "product", "direction"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class TradingHubCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        user_agent = self.config.get("user_agent") or "OEDS crawler/0.1 (+https://open-energy-data-server.readthedocs.io/)"
        self.session = build_session(user_agent)
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS report_rows (
                        report_id text NOT NULL,
                        row_number integer NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        source_url text NOT NULL,
                        payload_json text NOT NULL,
                        PRIMARY KEY (report_id, row_number, fetched_at)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS report_values (
                        report_id text NOT NULL,
                        row_number integer NOT NULL,
                        gas_day date,
                        status text,
                        unit text,
                        dimension text,
                        measure text NOT NULL,
                        value double precision,
                        fetched_at timestamp with time zone NOT NULL,
                        record_key text NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_the_values_day ON report_values (gas_day DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_the_values_report_measure ON report_values (report_id, measure)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_report_values AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY report_id, measure, dimension
                                ORDER BY gas_day DESC NULLS LAST, fetched_at DESC
                            ) AS rn
                        FROM report_values
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
                    CREATE OR REPLACE VIEW report_summary AS
                    SELECT
                        report_id,
                        count(*) AS value_rows,
                        min(gas_day) AS temporal_start,
                        max(gas_day) AS temporal_end,
                        max(fetched_at) AS last_fetch
                    FROM report_values
                    GROUP BY report_id
                    """
                )
            )

    def _date_window(self) -> tuple[datetime, datetime]:
        today = datetime.now(tz=timezone.utc).date()
        lookback_days = int(self.config.get("lookback_days", 45))
        return datetime.combine(today - timedelta(days=lookback_days), datetime.min.time(), tzinfo=timezone.utc), datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    def _format_the_date(self, value: datetime) -> str:
        return value.strftime("%d-%m-%Y")

    def _fetch_report(self, report_id: str, date_from: datetime, date_to: datetime) -> tuple[str, list[dict[str, str]]]:
        params = {"ReportId": report_id}
        if report_id not in {"PricesEnergyImbalancePreliminary", "PricesFlexibilityChargeIntraday"}:
            params["Start"] = self._format_the_date(date_from)
            params["End"] = self._format_the_date(date_to)
        response = self.session.get(BASE_URL, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        records = []
        for child in root:
            if local_name(child.tag) != report_id:
                continue
            record = {local_name(field.tag): (field.text or "").strip() for field in child}
            if record:
                records.append(record)
        return response.url, records

    def _normalize(self, report_id: str, records: list[dict[str, str]], fetched_at: datetime, source_url: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw_rows = []
        value_rows = []
        for row_number, record in enumerate(records, start=1):
            raw_rows.append(
                {
                    "report_id": report_id,
                    "row_number": row_number,
                    "fetched_at": fetched_at,
                    "source_url": source_url,
                    "payload_json": compact_json(record),
                }
            )
            normalized_keys = {key: normalize_column_name(key) for key in record}
            gas_day = None
            for key, normalized in normalized_keys.items():
                if normalized in DATE_COLUMNS:
                    parsed = pd.to_datetime(record.get(key), errors="coerce")
                    if not pd.isna(parsed):
                        gas_day = parsed.date()
                        break
            status = next((record[key] for key, normalized in normalized_keys.items() if normalized == "status"), None)
            unit = next((record[key] for key, normalized in normalized_keys.items() if normalized == "unit"), None)
            dimensions = []
            for key, normalized in normalized_keys.items():
                if normalized in NON_VALUE_COLUMNS:
                    continue
                if parse_number(record.get(key)) is None and record.get(key):
                    dimensions.append(f"{key}={record.get(key)}")
            dimension = "; ".join(dimensions) if dimensions else None
            for key, normalized in normalized_keys.items():
                if normalized in NON_VALUE_COLUMNS:
                    continue
                value = parse_number(record.get(key))
                if value is None:
                    continue
                value_rows.append(
                    {
                        "report_id": report_id,
                        "row_number": row_number,
                        "gas_day": gas_day,
                        "status": status,
                        "unit": unit,
                        "dimension": dimension,
                        "measure": key,
                        "value": value,
                        "fetched_at": fetched_at,
                        "record_key": stable_hash(report_id, row_number, key, gas_day, value),
                    }
                )
        return pd.DataFrame(raw_rows), pd.DataFrame(value_rows)

    def _replace_report_rows(self, report_id: str, raw_rows: pd.DataFrame, value_rows: pd.DataFrame, date_from: datetime, date_to: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM report_rows WHERE report_id = :report_id"), {"report_id": report_id})
            conn.execute(
                text(
                    """
                    DELETE FROM report_values
                    WHERE report_id = :report_id
                      AND (gas_day IS NULL OR (gas_day >= :date_from AND gas_day <= :date_to))
                    """
                ),
                {"report_id": report_id, "date_from": date_from.date(), "date_to": date_to.date()},
            )
            if not raw_rows.empty:
                raw_rows.to_sql("report_rows", conn, if_exists="append", index=False)
            if not value_rows.empty:
                value_rows.to_sql("report_values", conn, if_exists="append", index=False)

    def run(self):
        self._prepare_schema()
        failures: list[str] = []
        write_access_status(
            self.engine,
            source_name="Trading Hub Europe XML Interface",
            status="public",
            access_model="Public XML interface; User-Agent is mandatory per THE documentation",
            credentials_required=False,
            configured_credentials=False,
            message="Crawler sends a technical User-Agent and limits the date window by configuration.",
            docs_url=DOCS_URL,
        )
        date_from, date_to = self._date_window()
        reports = self.config.get("reports", DEFAULT_REPORTS)
        total_rows = 0
        for report_id in reports:
            try:
                source_url, records = self._fetch_report(report_id, date_from, date_to)
                raw_rows, value_rows = self._normalize(report_id, records, utc_now(), source_url)
                self._replace_report_rows(report_id, raw_rows, value_rows, date_from, date_to)
                total_rows += len(records)
            except Exception as exc:
                self.logger.error("Trading Hub Europe report %s failed: %s", report_id, exc)
                failures.append(str(report_id))
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": BASE_URL,
                "license": "Trading Hub Europe transparency data terms; review before republication",
                "description": "Trading Hub Europe gas market XML reports: imbalance prices, balancing gas, conversion and consumption.",
                "contact": "https://www.tradinghub.eu/en-gb/Contact",
                "temporal_start": date_from.isoformat(),
                "temporal_end": date_to.isoformat(),
            }
        )
        self.logger.info("Trading Hub Europe crawler wrote %s report rows.", total_rows)
        if failures:
            raise RuntimeError(f"Trading Hub Europe reports failed: {', '.join(failures)}")


def main(schema_name: str = "tradinghub"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    TradingHubCrawler("tradinghub", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
