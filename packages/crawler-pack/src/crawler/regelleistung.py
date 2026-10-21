# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
from typing import Any

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


log = logging.getLogger("regelleistung")
log.setLevel(logging.INFO)

API_BASE_URL = "https://www.regelleistung.net/apps/crds/api/v2"
DOCS_URL = "https://www.regelleistung.net/en-us/Data/Where-can-I-find-what-data"


class RegelleistungCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tender_files (
                        file_name text PRIMARY KEY,
                        control_block text,
                        date_range_type text,
                        file_type text,
                        product_type text,
                        market text,
                        date_range text,
                        source_url text,
                        discovered_at timestamp with time zone NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS file_rows (
                        file_name text NOT NULL,
                        sheet_name text NOT NULL,
                        row_number integer NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        payload_json text NOT NULL,
                        PRIMARY KEY (file_name, sheet_name, row_number, fetched_at)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS numeric_values (
                        file_name text NOT NULL,
                        sheet_name text NOT NULL,
                        row_number integer NOT NULL,
                        delivery_date timestamp with time zone,
                        product_type text,
                        market text,
                        measure text NOT NULL,
                        value double precision,
                        unit text,
                        fetched_at timestamp with time zone NOT NULL,
                        record_key text NOT NULL
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rl_values_date ON numeric_values (delivery_date DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rl_values_product ON numeric_values (product_type, market, measure)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW file_summary AS
                    SELECT
                        product_type,
                        market,
                        file_type,
                        count(*) AS files,
                        max(discovered_at) AS last_discovery
                    FROM tender_files
                    GROUP BY product_type, market, file_type
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_numeric_values AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY product_type, market, measure
                                ORDER BY delivery_date DESC NULLS LAST, fetched_at DESC
                            ) AS rn
                        FROM numeric_values
                    )
                    SELECT *
                    FROM ranked
                    WHERE rn = 1
                    """
                )
            )

    def _date_window(self) -> tuple[datetime, datetime]:
        today = datetime.now(tz=timezone.utc).date()
        lookback_days = int(self.config.get("lookback_days", 35))
        date_from = today - timedelta(days=lookback_days)
        return datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc), datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    def _query_files(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        params = {
            "from": date_from.date().isoformat(),
            "to": date_to.date().isoformat(),
            "productTypes": ",".join(self.config.get("product_types", ["FCR", "aFRR", "mFRR"])),
            "markets": ",".join(self.config.get("markets", ["CAPACITY", "ENERGY"])),
            "fileTypes": ",".join(self.config.get("file_types", ["RESULTS", "MAXIMUM_EXCHANGE_LIMIT"])),
            "pageSize": int(self.config.get("page_size", 1000)),
        }
        response = self.session.get(f"{API_BASE_URL}/tenders/files", params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return payload.get("value", [])

    def _upsert_files(self, files: list[dict[str, Any]]) -> None:
        if not files:
            return
        discovered_at = utc_now()
        rows = []
        for file_info in files:
            file_name = file_info.get("fileName")
            if not file_name:
                continue
            rows.append(
                {
                    "file_name": file_name,
                    "control_block": file_info.get("controlBlock"),
                    "date_range_type": file_info.get("dateRangeType"),
                    "file_type": file_info.get("fileType"),
                    "product_type": file_info.get("productType"),
                    "market": file_info.get("market"),
                    "date_range": file_info.get("dateRange"),
                    "source_url": f"{API_BASE_URL}/tenders/files/{file_name}",
                    "discovered_at": discovered_at,
                }
            )
        with self.engine.begin() as conn:
            for row in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO tender_files
                            (file_name, control_block, date_range_type, file_type, product_type, market, date_range, source_url, discovered_at)
                        VALUES
                            (:file_name, :control_block, :date_range_type, :file_type, :product_type, :market, :date_range, :source_url, :discovered_at)
                        ON CONFLICT (file_name) DO UPDATE SET
                            control_block = EXCLUDED.control_block,
                            date_range_type = EXCLUDED.date_range_type,
                            file_type = EXCLUDED.file_type,
                            product_type = EXCLUDED.product_type,
                            market = EXCLUDED.market,
                            date_range = EXCLUDED.date_range,
                            source_url = EXCLUDED.source_url,
                            discovered_at = EXCLUDED.discovered_at
                        """
                    ),
                    row,
                )

    def _download_file(self, file_name: str) -> bytes:
        response = self.session.get(f"{API_BASE_URL}/tenders/files/{file_name}", timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.content

    def _parse_workbook(self, file_name: str, content: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
        fetched_at = utc_now()
        workbook = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
        raw_rows = []
        numeric_rows = []
        for sheet_name, frame in workbook.items():
            frame = frame.dropna(how="all")
            if frame.empty:
                continue
            frame.columns = [str(column).strip() for column in frame.columns]
            normalized_columns = {column: normalize_column_name(column) for column in frame.columns}
            date_candidates = [
                column
                for column, normalized in normalized_columns.items()
                if normalized in {"delivery_date", "date", "date_from", "date_to", "lieferdatum", "ausschreibungstag"}
            ]
            product_candidates = [column for column, normalized in normalized_columns.items() if normalized in {"product_type", "product", "produkt"}]
            market_candidates = [column for column, normalized in normalized_columns.items() if normalized in {"market", "markt"}]
            for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
                payload = {column: row.get(column) for column in frame.columns if pd.notnull(row.get(column))}
                raw_rows.append(
                    {
                        "file_name": file_name,
                        "sheet_name": str(sheet_name),
                        "row_number": row_number,
                        "fetched_at": fetched_at,
                        "payload_json": compact_json(payload),
                    }
                )
                delivery_date = None
                for candidate in date_candidates:
                    parsed = pd.to_datetime(row.get(candidate), errors="coerce", utc=True)
                    if not pd.isna(parsed):
                        delivery_date = parsed.to_pydatetime()
                        break
                product_type = str(row.get(product_candidates[0])).strip() if product_candidates and pd.notnull(row.get(product_candidates[0])) else None
                market = str(row.get(market_candidates[0])).strip() if market_candidates and pd.notnull(row.get(market_candidates[0])) else None
                for column in frame.columns:
                    value = parse_number(row.get(column))
                    if value is None:
                        continue
                    normalized = normalized_columns[column]
                    if normalized in {"year", "month", "day"}:
                        continue
                    numeric_rows.append(
                        {
                            "file_name": file_name,
                            "sheet_name": str(sheet_name),
                            "row_number": row_number,
                            "delivery_date": delivery_date,
                            "product_type": product_type,
                            "market": market,
                            "measure": column,
                            "value": value,
                            "unit": None,
                            "fetched_at": fetched_at,
                            "record_key": stable_hash(file_name, sheet_name, row_number, column, value),
                        }
                    )
        return pd.DataFrame(raw_rows), pd.DataFrame(numeric_rows)

    def _write_file_content(self, file_name: str, raw_rows: pd.DataFrame, numeric_rows: pd.DataFrame) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM file_rows WHERE file_name = :file_name"), {"file_name": file_name})
            conn.execute(text("DELETE FROM numeric_values WHERE file_name = :file_name"), {"file_name": file_name})
            if not raw_rows.empty:
                raw_rows.to_sql("file_rows", conn, if_exists="append", index=False)
            if not numeric_rows.empty:
                numeric_rows.to_sql("numeric_values", conn, if_exists="append", index=False)

    def run(self):
        self._prepare_schema()
        failures: list[str] = []
        write_access_status(
            self.engine,
            source_name="regelleistung.net Datacenter",
            status="public",
            access_model="Public datacenter API for tender file discovery and downloads; BSP API credentials only for provider-specific workflows",
            credentials_required=False,
            configured_credentials=False,
            message="Public tender files are accessible without credentials. Use a clear User-Agent and keep request volume moderate.",
            docs_url=DOCS_URL,
        )

        date_from, date_to = self._date_window()
        files = self._query_files(date_from, date_to)
        self._upsert_files(files)

        max_files = int(self.config.get("max_files_per_run", 12))
        download_files = bool(self.config.get("download_files", True))
        downloaded = 0
        if download_files:
            for file_info in files[:max_files]:
                file_name = file_info.get("fileName")
                if not file_name:
                    continue
                try:
                    content = self._download_file(file_name)
                    raw_rows, numeric_rows = self._parse_workbook(file_name, content)
                    self._write_file_content(file_name, raw_rows, numeric_rows)
                    downloaded += 1
                except Exception as exc:
                    self.logger.error("Failed to download or parse %s: %s", file_name, exc)
                    failures.append(str(file_name))

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": API_BASE_URL,
                "license": "Public regelleistung.net data; review upstream terms before republication",
                "description": "Tender file discovery and selected workbook imports from regelleistung.net datacenter.",
                "contact": "https://www.regelleistung.net/en-us/Contact",
                "temporal_start": date_from.isoformat(),
                "temporal_end": date_to.isoformat(),
            }
        )
        self.logger.info("Regelleistung crawler discovered %s files and imported %s.", len(files), downloaded)
        if failures:
            raise RuntimeError(f"Regelleistung files failed: {', '.join(failures)}")


def main(schema_name: str = "regelleistung"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    RegelleistungCrawler("regelleistung", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
