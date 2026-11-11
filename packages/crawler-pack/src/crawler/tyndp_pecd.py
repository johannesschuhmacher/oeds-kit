# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hourly capacity factors of the Pan-European Climate Database (PECD) as
published with the ENTSO-E/ENTSOG TYNDP scenarios, one series of 8760 hours
per edition, target year, PECD zone, technology and climate year."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import math
import os
from pathlib import Path
import re
import zipfile

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, copy_insert, normalize_column_name, utc_now, write_access_status


EDITIONS = {
    # PECD 3.1, climate years 1982-2019 (rooftop and utility PV to 2020).
    "tyndp2024": {
        "url": "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/PECD.zip",
        "attribution": "TYNDP 2024 Scenarios",
        "docs_url": "https://2024.entsos-tyndp-scenarios.eu/download/",
    },
    # National Trends input, 30 weather scenarios per target year: WS001-WS030
    # for 2030, WS031-WS060 for 2035, WS061-WS090 for 2040, WS091-WS120 for 2050.
    "tyndp2026": {
        "url": "https://2026-data.entsos-tyndp-scenarios.eu/input/model-input/national-trends/PECD.zip",
        "attribution": "TYNDP 2026 Scenarios",
        "docs_url": "https://2026.entsos-tyndp-scenarios.eu/download/",
    },
}
HOURS = 8760

# Technology names in the file names -> stored technology.
TECHNOLOGIES = {
    "LFSolarPV": "solar_pv",
    "LFSolarPVRooftop": "solar_pv_rooftop",
    "LFSolarPVUtility": "solar_pv_utility",
    "Solar PV Rooftop": "solar_pv_rooftop",
    "Solar PV Utility": "solar_pv_utility",
    "Wind_Onshore": "wind_onshore",
    "Wind_Offshore": "wind_offshore",
    "CSP_noStorage": "csp_no_storage",
    "CSP_noStorage_0h_dispatched": "csp_no_storage",
    "CSP_withStorage_7h_preDispatch": "csp_storage_7h_predispatch",
    "CSP_withStorage_7h_dispatched": "csp_storage_7h_dispatched",
}
# TYNDP 2024: PECD/2030/PECD_Wind_Onshore_2030_DE00_edition 2023.2.csv. Its one
# .xlsx file (ITCS solar utility 2040) repeats a .csv and is not read.
NAME_2024 = re.compile(r"PECD_(?P<tech>.+)_(?P<year>20\d\d)_(?P<zone>[^_]+)_edition [\d.]+\.csv$")
# TYNDP 2026: DE00_CapacityFactors_Wind_Onshore_2030.csv, DKN6_OFF_CapacityFactors_...,
# Solar PV Rooftop DE00.csv
NAME_2026 = re.compile(r"(?P<zone>.+?)_CapacityFactors_(?P<tech>.+)_(?P<year>20\d\d)\.csv$")
NAME_2026_PV = re.compile(r"(?P<tech>Solar PV (Rooftop|Utility)) (?P<zone>.+)\.csv$")


def parse_member_name(name: str) -> dict | None:
    """Target year, zone and technology of a zip member, or None for other files.

    The target year is the folder (``PECD/2030/``); the 2026 solar files carry
    no year in their name.
    """
    parts = name.split("/")
    if name.startswith("__MACOSX") or len(parts) != 3 or not parts[1].isdigit():
        return None
    base = parts[2]
    match = NAME_2024.match(base) or NAME_2026.match(base) or NAME_2026_PV.match(base)
    if not match:
        return None
    source_technology = match.group("tech")
    return {
        "target_year": int(parts[1]),
        "zone": match.group("zone"),
        "technology": TECHNOLOGIES.get(source_technology, normalize_column_name(source_technology)),
        "source_technology": source_technology,
        "source_file": name,
    }


def parse_series(content: bytes) -> pd.DataFrame:
    """Columns ``Date``, ``Hour`` and one column per climate year.

    The files start with a block of metadata rows (country, zone, target
    year); the table starts at the row whose first cell is ``Date``.
    """
    raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str, skip_blank_lines=False)
    header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Date"][0]
    frame = raw.iloc[header_row + 1 :].copy()
    frame.columns = [str(column).strip() for column in raw.iloc[header_row]]
    frame = frame.loc[:, [column for column in frame.columns if column and column != "nan"]]
    frame = frame.dropna(subset=["Date"])
    if len(frame) != HOURS:
        raise ValueError(f"expected {HOURS} hourly rows, found {len(frame)}")
    return frame


def climate_year_label(column: str) -> str:
    """``1982.0`` (TYNDP 2024) -> ``1982``; ``WS061`` (TYNDP 2026) unchanged."""
    return column[:-2] if re.fullmatch(r"\d{4}\.0", column) else column


def _number(value: float) -> str:
    # Six decimals: capacity factors lie in [0, 1], and values such as
    # 6.95e-48 in the source files are below the range of real.
    return f"{value:.6f}".rstrip("0").rstrip(".")


def array_literal(values) -> str:
    """PostgreSQL array text for a ``real[]`` column; NaN becomes NULL."""
    return "{" + ",".join("NULL" if math.isnan(v) else _number(v) for v in values) + "}"


class TyndpPecdCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 120))
        self.data_dir = Path(os.getenv("OEDS_CRAWLER_DATA_DIR", "crawler/data")) / "tyndp_pecd"

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS capacity_factors (
                        edition text NOT NULL,
                        target_year integer NOT NULL,
                        zone text NOT NULL,
                        technology text NOT NULL,
                        climate_year text NOT NULL,
                        capacity_factor real[] NOT NULL,
                        source_technology text NOT NULL,
                        source_file text NOT NULL,
                        PRIMARY KEY (edition, target_year, zone, technology, climate_year)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS editions (
                        edition text PRIMARY KEY,
                        url text NOT NULL,
                        last_modified text,
                        content_length bigint,
                        files integer NOT NULL,
                        series integer NOT NULL,
                        loaded_at timestamp with time zone NOT NULL
                    )
                    """
                )
            )
            # One row per hour; filter on edition, zone and technology first.
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW capacity_factors_hourly AS
                    SELECT c.edition, c.target_year, c.zone, c.technology, c.climate_year,
                           h.hour_of_year::integer AS hour_of_year, h.capacity_factor
                    FROM capacity_factors c
                    CROSS JOIN LATERAL unnest(c.capacity_factor) WITH ORDINALITY AS h(capacity_factor, hour_of_year)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW series_summary AS
                    SELECT edition, target_year, technology, count(DISTINCT zone) AS zones,
                           count(DISTINCT climate_year) AS climate_years, count(*) AS series
                    FROM capacity_factors
                    GROUP BY edition, target_year, technology
                    """
                )
            )

    def _remote_version(self, url: str) -> tuple[str | None, int | None]:
        response = self.session.head(url, timeout=self.timeout_seconds, allow_redirects=True)
        response.raise_for_status()
        length = response.headers.get("Content-Length")
        return response.headers.get("Last-Modified"), int(length) if length else None

    def _download(self, edition: str, url: str) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / f"{edition}.zip"
        partial = target.with_suffix(".zip.part")
        with self.session.get(url, timeout=self.timeout_seconds, stream=True) as response:
            response.raise_for_status()
            with open(partial, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    handle.write(chunk)
        partial.replace(target)
        return target

    def _rows(self, edition: str, archive: zipfile.ZipFile):
        """Yield one DataFrame of series rows per zip member."""
        for name in archive.namelist():
            member = parse_member_name(name)
            if member is None:
                continue
            try:
                frame = parse_series(archive.read(name))
            except ValueError as error:
                raise ValueError(f"{edition} {name}: {error}") from error
            rows = []
            for column in frame.columns[2:]:
                values = pd.to_numeric(frame[column], errors="coerce").astype(float)
                rows.append({**member, "climate_year": climate_year_label(column), "capacity_factor": array_literal(values)})
            yield pd.DataFrame(rows).assign(edition=edition)

    def _load_edition(self, edition: str, settings: dict, last_modified: str | None, content_length: int | None) -> None:
        path = self._download(edition, settings["url"])
        files = series = 0
        try:
            with zipfile.ZipFile(path) as archive, self.engine.begin() as conn:
                conn.execute(text("DELETE FROM capacity_factors WHERE edition = :e"), {"e": edition})
                for frame in self._rows(edition, archive):
                    frame.to_sql("capacity_factors", conn, if_exists="append", index=False, method=copy_insert)
                    files += 1
                    series += len(frame)
                conn.execute(
                    text(
                        """
                        INSERT INTO editions (edition, url, last_modified, content_length, files, series, loaded_at)
                        VALUES (:edition, :url, :last_modified, :content_length, :files, :series, :loaded_at)
                        ON CONFLICT (edition) DO UPDATE SET
                            url = EXCLUDED.url, last_modified = EXCLUDED.last_modified,
                            content_length = EXCLUDED.content_length, files = EXCLUDED.files,
                            series = EXCLUDED.series, loaded_at = EXCLUDED.loaded_at
                        """
                    ),
                    {
                        "edition": edition, "url": settings["url"], "last_modified": last_modified,
                        "content_length": content_length, "files": files, "series": series, "loaded_at": utc_now(),
                    },
                )
        finally:
            path.unlink(missing_ok=True)
        self.logger.info("PECD %s: %s files, %s series.", edition, files, series)

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="TYNDP scenarios PECD",
            status="public",
            access_model="Public ZIP download from the ENTSOs TYNDP scenarios website",
            credentials_required=False,
            configured_credentials=False,
            message="CC BY 4.0; attribution 'TYNDP 2024 Scenarios' or 'TYNDP 2026 Scenarios'.",
            docs_url=EDITIONS["tyndp2026"]["docs_url"],
        )
        editions = self.config.get("editions", list(EDITIONS))
        with self.engine.connect() as conn:
            stored = {
                row.edition: (row.last_modified, row.content_length)
                for row in conn.execute(text("SELECT edition, last_modified, content_length FROM editions"))
            }
        for edition in editions:
            settings = EDITIONS[edition]
            version = self._remote_version(settings["url"])
            # The archives are 0.8-1.4 GB; load one again only when it changed.
            if stored.get(edition) == version:
                self.logger.info("PECD %s unchanged (%s).", edition, version[0])
                continue
            self._load_edition(edition, settings, *version)
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": ", ".join(EDITIONS[edition]["url"] for edition in editions),
                "license": "CC BY 4.0, " + " / ".join(EDITIONS[edition]["attribution"] for edition in editions),
                "description": "TYNDP PECD hourly capacity factors per PECD zone, technology, target and climate year.",
                "contact": "https://www.entsoe.eu/contact/",
            }
        )
