# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Monthly commodity prices of the World Bank Pink Sheet (coal, crude oil,
natural gas, LNG and other commodities) in nominal US dollars."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import re

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, copy_insert, utc_now, write_access_status


PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"
MONTHLY_LINK = re.compile(r'https://thedocs\.worldbank\.org/[^"\s]*CMO-Historical-Data-Monthly\.xlsx')
SHEET = "Monthly Prices"
# Commodities of the energy view: the workbook's column headers without
# footnote marks ("Coal, South African **").
ENERGY = [
    "Crude oil, average",
    "Crude oil, Brent",
    "Crude oil, Dubai",
    "Crude oil, WTI",
    "Coal, Australian",
    "Coal, South African",
    "Natural gas, US",
    "Natural gas, Europe",
    "Liquefied natural gas, Japan",
]


def parse_monthly_prices(content: bytes) -> pd.DataFrame:
    """One row per commodity and month from the ``Monthly Prices`` sheet.

    The sheet has four title rows, then a row of commodity names, a row of
    units (``($/bbl)``) and one row per month (``1960M01``). Missing values
    are written as ``…``.
    """
    raw = pd.read_excel(io.BytesIO(content), sheet_name=SHEET, header=None, dtype=object)
    header_row = raw.index[raw.iloc[:, 1].astype(str).str.startswith("Crude oil")][0]
    names = raw.iloc[header_row, 1:].tolist()
    units = raw.iloc[header_row + 1, 1:].tolist()
    body = raw.iloc[header_row + 2 :].copy()
    body = body[body.iloc[:, 0].astype(str).str.fullmatch(r"\d{4}M\d{2}")]
    rows = []
    for position, (name, unit) in enumerate(zip(names, units), start=1):
        if not isinstance(name, str) or not name.strip():
            continue
        values = pd.to_numeric(body.iloc[:, position], errors="coerce")
        rows.append(
            pd.DataFrame(
                {
                    "commodity": name.strip().rstrip(" *"),
                    "unit": str(unit).strip().strip("()") if isinstance(unit, str) else None,
                    "period": body.iloc[:, 0].astype(str).values,
                    "price": values.values,
                }
            )
        )
    frame = pd.concat(rows, ignore_index=True).dropna(subset=["price"])
    frame["year"] = frame["period"].str[:4].astype(int)
    frame["month"] = frame["period"].str[5:].astype(int)
    frame["period_start"] = pd.to_datetime({"year": frame["year"], "month": frame["month"], "day": 1}, utc=True)
    return frame[["commodity", "unit", "year", "month", "period_start", "price"]]


class WorldbankCommoditiesCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        energy = ", ".join("'" + name.replace("'", "''") + "'" for name in ENERGY)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS monthly_prices (
                        commodity text NOT NULL,
                        unit text,
                        year integer NOT NULL,
                        month integer NOT NULL,
                        period_start timestamp with time zone NOT NULL,
                        price double precision NOT NULL,
                        source_url text NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        PRIMARY KEY (commodity, year, month)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_wb_monthly_period ON monthly_prices (period_start DESC)"))
            conn.execute(
                text(
                    f"""
                    CREATE OR REPLACE VIEW energy_prices AS
                    SELECT commodity, unit, year, month, period_start, price
                    FROM monthly_prices
                    WHERE commodity IN ({energy})
                    """
                )
            )

    def _monthly_url(self) -> str:
        # The file URL changes with every monthly release, so it is read from the page.
        response = self.session.get(PAGE_URL, timeout=self.timeout_seconds)
        response.raise_for_status()
        match = MONTHLY_LINK.search(response.text)
        if not match:
            raise RuntimeError(f"No CMO-Historical-Data-Monthly.xlsx link on {PAGE_URL}")
        return match.group(0)

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="World Bank Pink Sheet",
            status="public",
            access_model="Public XLSX download",
            credentials_required=False,
            configured_credentials=False,
            message="World Bank Commodity Price Data (The Pink Sheet), CC BY 4.0; cite the World Bank as source.",
            docs_url=PAGE_URL,
        )
        source_url = self._monthly_url()
        response = self.session.get(source_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        frame = parse_monthly_prices(response.content)
        frame["source_url"] = source_url
        frame["fetched_at"] = utc_now()
        # The workbook holds the full history and revises recent months.
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM monthly_prices"))
            frame.to_sql("monthly_prices", conn, if_exists="append", index=False, method=copy_insert)
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": source_url,
                "license": "CC BY 4.0, World Bank Commodity Price Data (The Pink Sheet)",
                "description": "World Bank monthly commodity prices in nominal US dollars (energy, metals, agriculture).",
                "contact": PAGE_URL,
                "temporal_start": frame["period_start"].min().isoformat(),
                "temporal_end": frame["period_start"].max().isoformat(),
            }
        )
        self.logger.info("World Bank crawler wrote %s monthly prices for %s commodities.", len(frame), frame["commodity"].nunique())
