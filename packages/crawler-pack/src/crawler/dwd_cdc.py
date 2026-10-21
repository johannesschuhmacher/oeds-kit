# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timezone
import io
import logging
from typing import Any

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, parse_number, utc_now, write_access_status


log = logging.getLogger("dwd_cdc")
log.setLevel(logging.INFO)

BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/regional_averages_DE/monthly"
DOCS_URL = "https://www.dwd.de/EN/ourservices/cdc/cdc_ueberblick-klimadaten_en.html"

DEFAULT_VARIABLES = [
    {"id": "air_temperature_mean", "path": "air_temperature_mean", "prefix": "tm", "unit": "degC"},
    {"id": "precipitation", "path": "precipitation", "prefix": "rr", "unit": "mm"},
    {"id": "sunshine_duration", "path": "sunshine_duration", "prefix": "sd", "unit": "h"},
]


class DwdCdcCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS regional_monthly (
                        variable text NOT NULL,
                        unit text,
                        year integer NOT NULL,
                        month integer NOT NULL,
                        period_start timestamp with time zone NOT NULL,
                        region text NOT NULL,
                        value double precision,
                        source_url text NOT NULL,
                        source_created_at text,
                        fetched_at timestamp with time zone NOT NULL,
                        PRIMARY KEY (variable, year, month, region)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dwd_regional_period ON regional_monthly (period_start DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dwd_regional_region ON regional_monthly (region, variable)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW germany_monthly AS
                    SELECT *
                    FROM regional_monthly
                    WHERE region = 'Deutschland'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW regional_summary AS
                    SELECT
                        variable,
                        unit,
                        region,
                        count(*) AS observations,
                        min(period_start) AS temporal_start,
                        max(period_start) AS temporal_end,
                        max(fetched_at) AS last_fetch
                    FROM regional_monthly
                    GROUP BY variable, unit, region
                    """
                )
            )

    def _source_url(self, variable: dict[str, Any], month: int) -> str:
        return f"{BASE_URL}/{variable['path']}/regional_averages_{variable['prefix']}_{month:02d}.txt"

    def _fetch_variable_month(self, variable: dict[str, Any], month: int, fetched_at: datetime) -> pd.DataFrame:
        source_url = self._source_url(variable, month)
        response = self.session.get(source_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        text_body = response.content.decode("latin-1")
        lines = text_body.splitlines()
        source_created_at = lines[0].rsplit(":", 1)[-1].strip() if lines else None
        frame = pd.read_csv(io.StringIO(text_body), sep=";", skiprows=1, dtype=str)
        frame = frame.dropna(axis=1, how="all").dropna(how="all")
        frame.columns = [str(column).strip() for column in frame.columns]
        if "Jahr" not in frame.columns or "Monat" not in frame.columns:
            raise RuntimeError(f"DWD CDC file {source_url} did not contain Jahr/Monat columns.")
        value_columns = [column for column in frame.columns if column not in {"Jahr", "Monat"} and column.strip()]
        melted = frame.melt(id_vars=["Jahr", "Monat"], value_vars=value_columns, var_name="region", value_name="value")
        melted["year"] = pd.to_numeric(melted["Jahr"], errors="coerce").astype("Int64")
        melted["month"] = pd.to_numeric(melted["Monat"], errors="coerce").astype("Int64")
        melted = melted.dropna(subset=["year", "month"])
        melted["period_start"] = pd.to_datetime(
            {
                "year": melted["year"].astype(int),
                "month": melted["month"].astype(int),
                "day": 1,
            },
            utc=True,
        )
        melted["value"] = melted["value"].map(parse_number)
        return pd.DataFrame(
            {
                "variable": variable["id"],
                "unit": variable.get("unit"),
                "year": melted["year"].astype(int),
                "month": melted["month"].astype(int),
                "period_start": melted["period_start"].dt.to_pydatetime(),
                "region": melted["region"].astype(str),
                "value": melted["value"],
                "source_url": source_url,
                "source_created_at": source_created_at,
                "fetched_at": fetched_at,
            }
        )

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="DWD Climate Data Center",
            status="public",
            access_model="Public DWD Open Data HTTP download",
            credentials_required=False,
            configured_credentials=False,
            message="DWD CDC files are public. Respect DWD Open Data terms and attribution requirements.",
            docs_url=DOCS_URL,
        )
        fetched_at = utc_now()
        variables = self.config.get("variables", DEFAULT_VARIABLES)
        months = self.config.get("months", list(range(1, 13)))
        frames = []
        for variable in variables:
            for month in months:
                frames.append(self._fetch_variable_month(variable, int(month), fetched_at))
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM regional_monthly"))
            if not combined.empty:
                combined.to_sql("regional_monthly", conn, if_exists="append", index=False)
        temporal_start = combined["period_start"].min().isoformat() if not combined.empty else None
        temporal_end = combined["period_start"].max().isoformat() if not combined.empty else None
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": BASE_URL,
                "license": "DWD open data license terms; attribution required",
                "description": "DWD CDC monthly regional climate averages for German federal states and Germany.",
                "contact": "https://www.dwd.de/EN/service/contact/contact_node.html",
                "temporal_start": temporal_start,
                "temporal_end": temporal_end,
            }
        )
        self.logger.info("DWD CDC crawler wrote %s monthly regional observations.", len(combined))


def main(schema_name: str = "dwd_cdc"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    DwdCdcCrawler("dwd_cdc", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
