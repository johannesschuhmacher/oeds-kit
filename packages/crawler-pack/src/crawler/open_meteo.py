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
from crawler.common.crawler_utils import (
    build_session,
    config_or_env,
    has_credential,
    parse_number,
    utc_now,
    write_access_status,
)
from crawler.common.local_env import load_crawler_dotenv


log = logging.getLogger("open_meteo")
log.setLevel(logging.INFO)

DEFAULT_API_URL = "https://api.open-meteo.com/v1/dwd-icon"
DOCS_URL = "https://open-meteo.com/en/docs/dwd-api"

DEFAULT_LOCATIONS = [
    {"id": "berlin", "name": "Berlin", "latitude": 52.52, "longitude": 13.41},
    {"id": "hamburg", "name": "Hamburg", "latitude": 53.55, "longitude": 10.0},
    {"id": "munich", "name": "Munich", "latitude": 48.14, "longitude": 11.58},
    {"id": "essen", "name": "Essen", "latitude": 51.46, "longitude": 7.01},
    {"id": "cuxhaven", "name": "Cuxhaven", "latitude": 53.86, "longitude": 8.69},
]

DEFAULT_HOURLY_VARIABLES = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_speed_80m",
    "shortwave_radiation",
    "direct_radiation",
    "precipitation",
    "cloud_cover",
]


class OpenMeteoCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS locations (
                        location_id text PRIMARY KEY,
                        name text NOT NULL,
                        latitude double precision NOT NULL,
                        longitude double precision NOT NULL,
                        updated_at timestamp with time zone NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS hourly_forecast (
                        location_id text NOT NULL,
                        valid_time timestamp with time zone NOT NULL,
                        variable text NOT NULL,
                        value double precision,
                        unit text,
                        fetched_at timestamp with time zone NOT NULL,
                        PRIMARY KEY (location_id, valid_time, variable)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_open_meteo_forecast_time ON hourly_forecast (valid_time DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_open_meteo_forecast_var ON hourly_forecast (variable, location_id)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_hourly_forecast AS
                    WITH ranked AS (
                        SELECT
                            *,
                            row_number() OVER (
                                PARTITION BY location_id, variable
                                ORDER BY valid_time DESC, fetched_at DESC
                            ) AS rn
                        FROM hourly_forecast
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
                    CREATE OR REPLACE VIEW location_summary AS
                    SELECT
                        l.location_id,
                        l.name,
                        l.latitude,
                        l.longitude,
                        h.variable,
                        count(*) AS forecast_hours,
                        min(h.valid_time) AS temporal_start,
                        max(h.valid_time) AS temporal_end,
                        max(h.fetched_at) AS last_fetch
                    FROM locations l
                    LEFT JOIN hourly_forecast h ON h.location_id = l.location_id
                    GROUP BY l.location_id, l.name, l.latitude, l.longitude, h.variable
                    """
                )
            )

    def _api_key(self) -> str | None:
        value = config_or_env(self.config, "api_key", "OPEN_METEO_API_KEY")
        return str(value) if has_credential(value) else None

    def _fetch_location(self, location: dict[str, Any], fetched_at: datetime) -> pd.DataFrame:
        hourly_variables = self.config.get("hourly_variables", DEFAULT_HOURLY_VARIABLES)
        params = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "hourly": ",".join(hourly_variables),
            "timezone": "UTC",
            "forecast_days": int(self.config.get("forecast_days", 5)),
            "past_days": int(self.config.get("past_days", 1)),
        }
        api_key = self._api_key()
        if api_key:
            params["apikey"] = api_key
        response = self.session.get(self.config.get("api_url", DEFAULT_API_URL), params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        hourly = payload.get("hourly", {})
        units = payload.get("hourly_units", {})
        times = pd.to_datetime(hourly.get("time", []), utc=True, errors="coerce")
        rows = []
        for variable in hourly_variables:
            values = hourly.get(variable, [])
            for valid_time, value in zip(times, values, strict=False):
                if pd.isna(valid_time):
                    continue
                rows.append(
                    {
                        "location_id": location["id"],
                        "valid_time": valid_time.to_pydatetime(),
                        "variable": variable,
                        "value": parse_number(value),
                        "unit": units.get(variable),
                        "fetched_at": fetched_at,
                    }
                )
        return pd.DataFrame(rows)

    def run(self):
        self._prepare_schema()
        api_key = self._api_key()
        write_access_status(
            self.engine,
            source_name="Open-Meteo",
            status="configured" if api_key else "public",
            access_model="No API key for non-commercial fair use; API key required for commercial plans",
            credentials_required=False,
            configured_credentials=bool(api_key),
            message="Using Open-Meteo forecast API with optional OPEN_METEO_API_KEY.",
            docs_url=DOCS_URL,
        )
        fetched_at = utc_now()
        locations = self.config.get("locations", DEFAULT_LOCATIONS)
        location_frame = pd.DataFrame(
            [
                {
                    "location_id": location["id"],
                    "name": location["name"],
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "updated_at": fetched_at,
                }
                for location in locations
            ]
        )
        frames = [self._fetch_location(location, fetched_at) for location in locations]
        forecast = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM locations"))
            if not location_frame.empty:
                location_frame.to_sql("locations", conn, if_exists="append", index=False)
            if not forecast.empty:
                min_time = forecast["valid_time"].min()
                max_time = forecast["valid_time"].max()
                conn.execute(
                    text(
                        """
                        DELETE FROM hourly_forecast
                        WHERE valid_time >= :min_time AND valid_time <= :max_time
                        """
                    ),
                    {"min_time": min_time, "max_time": max_time},
                )
                forecast.to_sql("hourly_forecast", conn, if_exists="append", index=False)
        temporal_start = forecast["valid_time"].min().isoformat() if not forecast.empty else None
        temporal_end = forecast["valid_time"].max().isoformat() if not forecast.empty else None
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": self.config.get("api_url", DEFAULT_API_URL),
                "license": "Open-Meteo terms; API source attribution required where applicable",
                "description": "Open-Meteo DWD ICON hourly weather forecasts for energy-relevant German locations.",
                "contact": "https://open-meteo.com/",
                "temporal_start": temporal_start,
                "temporal_end": temporal_end,
            }
        )
        self.logger.info("Open-Meteo crawler wrote %s hourly forecast values.", len(forecast))


def main(schema_name: str = "open_meteo"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    OpenMeteoCrawler("open_meteo", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
