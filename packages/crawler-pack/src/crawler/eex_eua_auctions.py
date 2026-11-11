# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Results of the EU ETS primary market auctions at EEX (auction clearing
price of EU allowances, volumes, bids) from the yearly EEX auction reports.

EEX's terms allow no systematic republication of substantial parts of its
market data without permission, so keep this schema off public dashboards.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, copy_insert, utc_now, write_access_status


REPORT_URL = "https://public.eex-group.com/eex/eua-auction-report/emission-spot-primary-market-auction-report-{year}-data.xlsx"
DOCS_URL = "https://www.eex.com/en/market-data/environmentals/eu-ets-auctions"
FIRST_YEAR = 2020  # earliest yearly report on public.eex-group.com
# Report header (without the euro sign and unit) -> column; the report has
# one column per member state after these, which are not loaded.
COLUMNS = {
    "Date": "auction_date",
    "Time": "published_at",
    "Auction Name": "auction_name",
    "Contract": "contract",
    "Status": "status",
    "Auction Price": "auction_price",
    "Minimum Bid": "minimum_bid",
    "Maximum Bid": "maximum_bid",
    "Mean": "mean_bid",
    "Median": "median_bid",
    "Auction Volume": "auction_volume",
    "Total Amount of Bids": "total_bid_volume",
    "Number of bids submitted": "bids_submitted",
    "Number of successful bids": "bids_successful",
    "Cover Ratio": "cover_ratio",
    "Total Number of Bidders": "bidders",
    "Number of Successful Bidders": "bidders_successful",
    "Total Revenue": "total_revenue",
    "Country": "zone",
    "Zone": "zone",
}
NUMERIC = [
    "auction_price", "minimum_bid", "maximum_bid", "mean_bid", "median_bid", "auction_volume",
    "total_bid_volume", "bids_submitted", "bids_successful", "cover_ratio", "bidders",
    "bidders_successful", "total_revenue",
]


def _column(header) -> str | None:
    if not isinstance(header, str):
        return None
    for prefix, column in COLUMNS.items():
        if header == prefix or header.startswith(prefix + " "):
            return column
    return None


def parse_auction_report(content: bytes) -> pd.DataFrame:
    """One row per auction from every sheet of a yearly report.

    Each sheet (``Primary Market Auction`` until 2025, ``EU ETS1`` from 2026)
    has a few title rows, the header row starting with ``Date`` in the second
    column and one row per auction, newest first. ``market`` is the sheet name.
    """
    frames = []
    for market, raw in pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object).items():
        header_rows = raw.index[raw.iloc[:, 1] == "Date"]
        if len(header_rows) == 0:
            continue
        header_row = header_rows[0]
        columns = {position: _column(name) for position, name in raw.iloc[header_row].items()}
        columns = {position: name for position, name in columns.items() if name}
        body = raw.iloc[header_row + 1 :][list(columns)].rename(columns=columns)
        body = body.dropna(subset=["auction_date"])
        body.insert(0, "market", market)
        frames.append(body)
    frame = pd.concat(frames, ignore_index=True).reindex(columns=["market", *dict.fromkeys(COLUMNS.values())])
    frame["auction_date"] = pd.to_datetime(frame["auction_date"]).dt.date
    frame["published_at"] = pd.to_datetime(frame["published_at"])
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


class EexEuaAuctionsCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 60))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auctions (
                        market text NOT NULL,
                        auction_date date NOT NULL,
                        published_at timestamp without time zone,
                        auction_name text NOT NULL,
                        contract text NOT NULL,
                        status text,
                        auction_price double precision,
                        minimum_bid double precision,
                        maximum_bid double precision,
                        mean_bid double precision,
                        median_bid double precision,
                        auction_volume double precision,
                        total_bid_volume double precision,
                        bids_submitted double precision,
                        bids_successful double precision,
                        cover_ratio double precision,
                        bidders double precision,
                        bidders_successful double precision,
                        total_revenue double precision,
                        zone text,
                        source_url text NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        PRIMARY KEY (auction_date, auction_name, contract)
                    )
                    """
                )
            )
            # Volume-weighted clearing price of the successful EUA auctions per day
            # (contract T3PA; EAA3 are aviation allowances, auctioned until 2024).
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW eua_daily_price AS
                    SELECT
                        auction_date,
                        sum(auction_price * auction_volume) / sum(auction_volume) AS price_eur_per_t,
                        sum(auction_volume) AS volume_t,
                        count(*) AS auctions
                    FROM auctions
                    WHERE contract = 'T3PA' AND status = 'successful' AND auction_volume > 0
                    GROUP BY auction_date
                    """
                )
            )

    def _fetch_year(self, year: int) -> pd.DataFrame | None:
        url = REPORT_URL.format(year=year)
        response = self.session.get(url, timeout=self.timeout_seconds)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        frame = parse_auction_report(response.content)
        frame["source_url"] = url
        return frame

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="EEX EU ETS primary auctions",
            status="public",
            access_model="Public yearly XLSX auction reports",
            credentials_required=False,
            configured_credentials=False,
            message="EEX market data: no systematic republication without EEX permission; keep off public dashboards.",
            docs_url=DOCS_URL,
        )
        first_year = int(self.config.get("start_year", FIRST_YEAR))
        current_year = datetime.now(tz=timezone.utc).year
        # A new year's report appears with its first auction in January.
        years = list(range(first_year, current_year + 1))
        frames = []
        for year in years:
            frame = self._fetch_year(year)
            if frame is None:
                if year != current_year:
                    raise RuntimeError(f"EEX auction report {REPORT_URL.format(year=year)} not found")
                self.logger.info("No EEX auction report for %s yet.", year)
                continue
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True)
        combined["fetched_at"] = utc_now()
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM auctions"))
            combined.to_sql("auctions", conn, if_exists="append", index=False, method=copy_insert)
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": DOCS_URL,
                "license": "EEX terms of use; no systematic republication without permission",
                "description": "EEX EU ETS primary market auction results (clearing price, volume, bids).",
                "contact": "datasource@eex-group.com",
                "temporal_start": pd.Timestamp(combined["auction_date"].min()).tz_localize("UTC").isoformat(),
                "temporal_end": pd.Timestamp(combined["auction_date"].max()).tz_localize("UTC").isoformat(),
            }
        )
        self.logger.info("EEX auction crawler wrote %s auctions for %s to %s.", len(combined), years[0], years[-1])
