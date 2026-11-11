# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cost and technology assumptions of PyPSA technology-data
(https://github.com/PyPSA/technology-data), one ``outputs/costs_<year>.csv``
per release and assumption year."""

from __future__ import annotations

from datetime import datetime, timezone
import io

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, copy_insert, utc_now, write_access_status


REPO = "PyPSA/technology-data"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"
RAW_URL = "https://raw.githubusercontent.com/" + REPO + "/{version}/outputs/costs_{year}.csv"
DOCS_URL = "https://technology-data.readthedocs.io"
DEFAULT_YEARS = list(range(2020, 2051, 5))
COLUMNS = ["technology", "parameter", "value", "unit", "source", "further_description", "currency_year"]


def parse_costs_csv(content: bytes) -> pd.DataFrame:
    """Rows of one costs file in the table's column names.

    Releases before v0.7 have no ``currency_year`` column; it stays empty.
    """
    frame = pd.read_csv(io.BytesIO(content), dtype={"unit": str, "source": str, "further description": str})
    frame = frame.rename(columns={"further description": "further_description"})
    frame = frame.reindex(columns=COLUMNS)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["currency_year"] = pd.to_numeric(frame["currency_year"], errors="coerce").astype("Int64")
    return frame


class PypsaTechnologyDataCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 60))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS costs (
                        version text NOT NULL,
                        year integer NOT NULL,
                        technology text NOT NULL,
                        parameter text NOT NULL,
                        value double precision,
                        unit text,
                        source text,
                        further_description text,
                        currency_year integer,
                        PRIMARY KEY (version, year, technology, parameter)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS releases (
                        version text PRIMARY KEY,
                        published_at timestamp with time zone,
                        years integer[] NOT NULL,
                        fetched_at timestamp with time zone NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_costs AS
                    SELECT c.*
                    FROM costs c
                    WHERE c.version = (SELECT version FROM releases ORDER BY published_at DESC LIMIT 1)
                    """
                )
            )

    def _releases(self) -> list[dict]:
        response = self.session.get(RELEASES_URL, params={"per_page": 100}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return [
            {"version": release["tag_name"], "published_at": release["published_at"]}
            for release in response.json()
            if not release.get("draft") and not release.get("prerelease")
        ]

    def _load_release(self, version: str, years: list[int]) -> pd.DataFrame:
        frames = []
        for year in years:
            response = self.session.get(RAW_URL.format(version=version, year=year), timeout=self.timeout_seconds)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            frame = parse_costs_csv(response.content)
            frame.insert(0, "year", year)
            frames.append(frame)
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined.insert(0, "version", version)
        return combined

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="PyPSA technology-data",
            status="public",
            access_model="Public GitHub release files",
            credentials_required=False,
            configured_credentials=False,
            message="Compiled cost assumptions; the licences of the underlying sources apply (see the source column).",
            docs_url=DOCS_URL,
        )
        years = [int(year) for year in self.config.get("years", DEFAULT_YEARS)]
        releases = self._releases()
        wanted = self.config.get("versions")
        if wanted:
            releases = [release for release in releases if release["version"] in set(wanted)]
        with self.engine.connect() as conn:
            loaded = {row[0] for row in conn.execute(text("SELECT version FROM releases"))}
        # Release files never change, so a run only loads releases not seen before.
        new_releases = [release for release in releases if release["version"] not in loaded]
        fetched_at = utc_now()
        for release in new_releases:
            frame = self._load_release(release["version"], years)
            loaded_years = sorted(frame["year"].unique().tolist()) if not frame.empty else []
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM costs WHERE version = :v"), {"v": release["version"]})
                if not frame.empty:
                    frame.to_sql("costs", conn, if_exists="append", index=False, method=copy_insert)
                conn.execute(
                    text(
                        "INSERT INTO releases (version, published_at, years, fetched_at) "
                        "VALUES (:version, :published_at, :years, :fetched_at)"
                    ),
                    {**release, "years": [int(y) for y in loaded_years], "fetched_at": fetched_at},
                )
            self.logger.info("technology-data %s: %s rows for years %s", release["version"], len(frame), loaded_years)
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": f"https://github.com/{REPO}",
                "license": "Code GPL-3.0; data under the terms of the cited sources",
                "description": "PyPSA technology-data cost and technology assumptions per release and year.",
                "contact": f"https://github.com/{REPO}/issues",
                "temporal_start": f"{min(years)}-01-01T00:00:00+00:00",
                "temporal_end": f"{max(years)}-01-01T00:00:00+00:00",
            }
        )
        self.logger.info("technology-data crawler loaded %s new releases.", len(new_releases))
