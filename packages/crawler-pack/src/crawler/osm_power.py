# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import build_session, compact_json, stable_hash, utc_now, write_access_status


log = logging.getLogger("osm_power")
log.setLevel(logging.INFO)

DOCS_URL = "https://operations.osmfoundation.org/policies/api/"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_BBOX = [47.2, 5.5, 55.2, 15.5]  # south, west, north, east: Germany-sized extraction.
DEFAULT_POWER_TAGS = ["plant", "generator", "substation"]


class OsmPowerCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 180))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS power_features (
                        osm_type text NOT NULL,
                        osm_id bigint NOT NULL,
                        power text,
                        name text,
                        operator text,
                        voltage text,
                        source text,
                        latitude double precision,
                        longitude double precision,
                        fetched_at timestamp with time zone NOT NULL,
                        tags_json text NOT NULL,
                        PRIMARY KEY (osm_type, osm_id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_osm_power_tag ON power_features (power)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_osm_power_location ON power_features (latitude, longitude)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW power_feature_summary AS
                    SELECT
                        power,
                        count(*) AS features,
                        max(fetched_at) AS last_fetch
                    FROM power_features
                    GROUP BY power
                    """
                )
            )

    def _build_query(self) -> str:
        bbox = self.config.get("bbox", DEFAULT_BBOX)
        if len(bbox) != 4:
            raise ValueError("osm_power.bbox must contain [south, west, north, east].")
        south, west, north, east = bbox
        power_tags = self.config.get("power_tags", DEFAULT_POWER_TAGS)
        power_regex = "^(" + "|".join(str(tag) for tag in power_tags) + ")$"
        timeout = int(self.config.get("overpass_timeout_seconds", 120))
        return f"""
        [out:json][timeout:{timeout}];
        (
          node["power"~"{power_regex}"]({south},{west},{north},{east});
          way["power"~"{power_regex}"]({south},{west},{north},{east});
          relation["power"~"{power_regex}"]({south},{west},{north},{east});
        );
        out tags center;
        """

    def _fetch_features(self) -> list[dict[str, Any]]:
        response = self.session.post(
            self.config.get("overpass_url", DEFAULT_OVERPASS_URL),
            data={"data": self._build_query()},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        elements = payload.get("elements", [])
        max_elements = int(self.config.get("max_elements", 50000))
        if len(elements) > max_elements:
            self.logger.warning("OSM Overpass returned %s elements; truncating to %s.", len(elements), max_elements)
            elements = elements[:max_elements]
        return elements

    def _normalize(self, elements: list[dict[str, Any]]) -> pd.DataFrame:
        fetched_at = utc_now()
        rows = []
        for element in elements:
            tags = element.get("tags", {})
            center = element.get("center", {})
            latitude = element.get("lat", center.get("lat"))
            longitude = element.get("lon", center.get("lon"))
            rows.append(
                {
                    "osm_type": element.get("type"),
                    "osm_id": element.get("id"),
                    "power": tags.get("power"),
                    "name": tags.get("name"),
                    "operator": tags.get("operator"),
                    "voltage": tags.get("voltage"),
                    "source": tags.get("source"),
                    "latitude": latitude,
                    "longitude": longitude,
                    "fetched_at": fetched_at,
                    "tags_json": compact_json(tags),
                }
            )
        return pd.DataFrame(rows)

    def run(self):
        self._prepare_schema()
        write_access_status(
            self.engine,
            source_name="OpenStreetMap / Overpass power data",
            status="public",
            access_model="Public OSM/Overpass read access; heavy users should use planet/extracts or their own server",
            credentials_required=False,
            configured_credentials=False,
            message="Crawler identifies itself with a User-Agent and limits the default query to selected power tags.",
            docs_url=DOCS_URL,
        )
        elements = self._fetch_features()
        frame = self._normalize(elements)
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM power_features"))
            if not frame.empty:
                frame.to_sql("power_features", conn, if_exists="append", index=False)
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": self.config.get("overpass_url", DEFAULT_OVERPASS_URL),
                "license": "OpenStreetMap data: ODbL; attribution required",
                "description": "OpenStreetMap power infrastructure features extracted via Overpass.",
                "contact": "https://www.openstreetmap.org/",
            }
        )
        self.logger.info("OSM power crawler wrote %s features.", len(frame))


def main(schema_name: str = "osm_power"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    OsmPowerCrawler("osm_power", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
