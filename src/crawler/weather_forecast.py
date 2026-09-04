# SPDX-FileCopyrightText: OpenData Developers
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import insert

from crawler.common.base_crawler import BaseCrawler


class WeatherForecastCrawler(BaseCrawler):
    SOURCE_URL = "https://api.open-meteo.com/v1/dwd-icon"
    DOCS_URL = "https://open-meteo.com/en/docs/dwd-api"

    HOURLY_VARIABLES = [
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "precipitation_probability",
        "precipitation",
        "cloud_cover",
        "wind_speed_10m",
        "wind_speed_80m",
        "wind_gusts_10m",
        "wind_direction_10m",
        "shortwave_radiation",
        "direct_radiation",
        "diffuse_radiation",
        "weather_code",
    ]

    DEFAULT_LOCATIONS = [
        {
            "location_id": "berlin",
            "name": "Berlin",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Berlin",
            "location_type": "load_center",
            "latitude": 52.52,
            "longitude": 13.405,
            "aggregation_weight": 1.3,
            "enabled": True,
        },
        {
            "location_id": "hamburg",
            "name": "Hamburg",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Hamburg",
            "location_type": "wind_load_hub",
            "latitude": 53.5511,
            "longitude": 9.9937,
            "aggregation_weight": 1.2,
            "enabled": True,
        },
        {
            "location_id": "frankfurt",
            "name": "Frankfurt am Main",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Hesse",
            "location_type": "load_center",
            "latitude": 50.1109,
            "longitude": 8.6821,
            "aggregation_weight": 1.1,
            "enabled": True,
        },
        {
            "location_id": "munich",
            "name": "Munich",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Bavaria",
            "location_type": "load_center",
            "latitude": 48.1372,
            "longitude": 11.5756,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "freiburg",
            "name": "Freiburg",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Baden-Wurttemberg",
            "location_type": "solar_hub",
            "latitude": 47.999,
            "longitude": 7.8421,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "cuxhaven",
            "name": "Cuxhaven",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Lower Saxony",
            "location_type": "offshore_wind_hub",
            "latitude": 53.8617,
            "longitude": 8.6942,
            "aggregation_weight": 1.4,
            "enabled": True,
        },
        {
            "location_id": "leipzig",
            "name": "Leipzig",
            "country_code": "DE",
            "country_name": "Germany",
            "region": "Saxony",
            "location_type": "load_center",
            "latitude": 51.3397,
            "longitude": 12.3731,
            "aggregation_weight": 0.9,
            "enabled": True,
        },
        {
            "location_id": "vienna",
            "name": "Vienna",
            "country_code": "AT",
            "country_name": "Austria",
            "region": "Vienna",
            "location_type": "capital",
            "latitude": 48.2082,
            "longitude": 16.3738,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "zurich",
            "name": "Zurich",
            "country_code": "CH",
            "country_name": "Switzerland",
            "region": "Zurich",
            "location_type": "capital_region",
            "latitude": 47.3769,
            "longitude": 8.5417,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "amsterdam",
            "name": "Amsterdam",
            "country_code": "NL",
            "country_name": "Netherlands",
            "region": "North Holland",
            "location_type": "capital",
            "latitude": 52.3676,
            "longitude": 4.9041,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "brussels",
            "name": "Brussels",
            "country_code": "BE",
            "country_name": "Belgium",
            "region": "Brussels",
            "location_type": "capital",
            "latitude": 50.8503,
            "longitude": 4.3517,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "copenhagen",
            "name": "Copenhagen",
            "country_code": "DK",
            "country_name": "Denmark",
            "region": "Capital Region",
            "location_type": "capital",
            "latitude": 55.6761,
            "longitude": 12.5683,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "paris",
            "name": "Paris",
            "country_code": "FR",
            "country_name": "France",
            "region": "Ile-de-France",
            "location_type": "capital",
            "latitude": 48.8566,
            "longitude": 2.3522,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "warsaw",
            "name": "Warsaw",
            "country_code": "PL",
            "country_name": "Poland",
            "region": "Masovian",
            "location_type": "capital",
            "latitude": 52.2297,
            "longitude": 21.0122,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
        {
            "location_id": "prague",
            "name": "Prague",
            "country_code": "CZ",
            "country_name": "Czechia",
            "region": "Prague",
            "location_type": "capital",
            "latitude": 50.0755,
            "longitude": 14.4378,
            "aggregation_weight": 1.0,
            "enabled": True,
        },
    ]

    ENTSOE_COUNTRY_ALIASES = [
        {"entsoe_area_name": "Austria (AT)", "country_code": "AT", "country_name": "Austria"},
        {"entsoe_area_name": "Belgium (BE)", "country_code": "BE", "country_name": "Belgium"},
        {"entsoe_area_name": "Czech Republic (CZ)", "country_code": "CZ", "country_name": "Czechia"},
        {"entsoe_area_name": "DE(50Hertz)", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "DE(Amprion)", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "DE(TenneT GER)", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "DE(TransnetBW)", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "DE-LU", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "Denmark (DK)", "country_code": "DK", "country_name": "Denmark"},
        {"entsoe_area_name": "DK", "country_code": "DK", "country_name": "Denmark"},
        {"entsoe_area_name": "DK1", "country_code": "DK", "country_name": "Denmark"},
        {"entsoe_area_name": "DK2", "country_code": "DK", "country_name": "Denmark"},
        {"entsoe_area_name": "France (FR)", "country_code": "FR", "country_name": "France"},
        {"entsoe_area_name": "Germany (DE)", "country_code": "DE", "country_name": "Germany"},
        {"entsoe_area_name": "Netherlands (NL)", "country_code": "NL", "country_name": "Netherlands"},
        {"entsoe_area_name": "Poland (PL)", "country_code": "PL", "country_name": "Poland"},
        {"entsoe_area_name": "Switzerland (CH)", "country_code": "CH", "country_name": "Switzerland"},
    ]

    WMO_LABELS = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Freezing rain",
        71: "Light snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        85: "Snow showers",
        86: "Snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with hail",
    }

    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.schema_name = self.get("schema_name")
        self.metadata = MetaData(schema=self.schema_name)
        self.session = requests.Session()
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 45))
        self.forecast_hours = int(self.config.get("forecast_hours", 120))
        self.past_hours = int(self.config.get("past_hours", 24))
        self.locations_config = self.config.get("locations", self.DEFAULT_LOCATIONS)

        self.locations_table = Table(
            "locations",
            self.metadata,
            Column("location_id", String, primary_key=True),
            Column("name", String, nullable=False),
            Column("country_code", String, nullable=False),
            Column("country_name", String, nullable=False),
            Column("region", String, nullable=False),
            Column("location_type", String, nullable=False),
            Column("latitude", Float, nullable=False),
            Column("longitude", Float, nullable=False),
            Column("elevation_m", Float),
            Column("aggregation_weight", Float, nullable=False, default=1.0),
            Column("enabled", Boolean, nullable=False, default=True),
        )

        self.entsoe_country_aliases_table = Table(
            "entsoe_country_aliases",
            self.metadata,
            Column("entsoe_area_name", String, primary_key=True),
            Column("country_code", String, nullable=False),
            Column("country_name", String, nullable=False),
        )

        self.hourly_forecast_table = Table(
            "hourly_forecast",
            self.metadata,
            Column("location_id", String, nullable=False, primary_key=True),
            Column("weather_model", String, nullable=False, primary_key=True),
            Column("retrieved_at", DateTime(timezone=True), nullable=False, primary_key=True),
            Column("forecast_time", DateTime(timezone=True), nullable=False, primary_key=True),
            Column("temperature_2m_c", Float),
            Column("apparent_temperature_c", Float),
            Column("relative_humidity_2m_pct", Float),
            Column("precipitation_probability_pct", Float),
            Column("precipitation_mm", Float),
            Column("cloud_cover_pct", Float),
            Column("wind_speed_10m_ms", Float),
            Column("wind_speed_80m_ms", Float),
            Column("wind_gusts_10m_ms", Float),
            Column("wind_direction_10m_deg", Float),
            Column("shortwave_radiation_wm2", Float),
            Column("direct_radiation_wm2", Float),
            Column("diffuse_radiation_wm2", Float),
            Column("weather_code", Integer),
            Column("weather_label", String),
            Column("heating_degree_18c", Float),
            Column("cooling_degree_22c", Float),
            Column("solar_generation_index", Float),
            Column("wind_generation_index", Float),
            Column("renewables_weather_index", Float),
            Column("load_weather_index", Float),
        )

    def _get_locations(self) -> list[dict[str, Any]]:
        locations = []
        for raw_location in self.locations_config:
            location = dict(raw_location)
            if not location.get("enabled", True):
                continue

            required_fields = [
                "location_id",
                "name",
                "country_code",
                "country_name",
                "region",
                "location_type",
                "latitude",
                "longitude",
            ]
            missing = [field for field in required_fields if field not in location]
            if missing:
                raise ValueError(
                    f"Location config '{location.get('location_id', '<unknown>')}' misses fields: {', '.join(missing)}"
                )

            location["aggregation_weight"] = float(location.get("aggregation_weight", 1.0))
            location["enabled"] = bool(location.get("enabled", True))
            locations.append(location)

        if not locations:
            raise ValueError("At least one weather location must be enabled.")

        return locations

    def _prepare_schema(self) -> None:
        self.metadata.create_all(
            self.engine,
            tables=[self.locations_table, self.entsoe_country_aliases_table, self.hourly_forecast_table],
        )

        with self.engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "SELECT public.create_hypertable('hourly_forecast', 'forecast_time', if_not_exists => TRUE, migrate_data => TRUE);"
                    )
                )
            except Exception as exc:
                self.logger.warning(f"Could not create hypertable for hourly_forecast: {exc}")

            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_hourly_forecast_location_time ON hourly_forecast (location_id, forecast_time DESC);"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_hourly_forecast_retrieved ON hourly_forecast (retrieved_at DESC);"
                )
            )

            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_hourly_forecast AS
                    WITH ranked AS (
                        SELECT
                            hf.location_id,
                            l.name AS location_name,
                            l.country_code,
                            l.country_name,
                            l.region,
                            l.location_type,
                            l.latitude,
                            l.longitude,
                            l.elevation_m,
                            l.aggregation_weight,
                            hf.weather_model,
                            hf.retrieved_at,
                            hf.forecast_time,
                            hf.temperature_2m_c,
                            hf.apparent_temperature_c,
                            hf.relative_humidity_2m_pct,
                            hf.precipitation_probability_pct,
                            hf.precipitation_mm,
                            hf.cloud_cover_pct,
                            hf.wind_speed_10m_ms,
                            hf.wind_speed_80m_ms,
                            hf.wind_gusts_10m_ms,
                            hf.wind_direction_10m_deg,
                            hf.shortwave_radiation_wm2,
                            hf.direct_radiation_wm2,
                            hf.diffuse_radiation_wm2,
                            hf.weather_code,
                            hf.weather_label,
                            hf.heating_degree_18c,
                            hf.cooling_degree_22c,
                            hf.solar_generation_index,
                            hf.wind_generation_index,
                            hf.renewables_weather_index,
                            hf.load_weather_index,
                            ROW_NUMBER() OVER (
                                PARTITION BY hf.location_id, hf.forecast_time
                                ORDER BY hf.retrieved_at DESC
                            ) AS rn
                        FROM hourly_forecast hf
                        JOIN locations l ON l.location_id = hf.location_id
                        WHERE l.enabled = TRUE
                    )
                    SELECT *
                    FROM ranked
                    WHERE rn = 1;
                    """
                )
            )

            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW latest_country_hourly_forecast AS
                    SELECT
                        country_code,
                        country_name,
                        forecast_time,
                        MAX(retrieved_at) AS retrieved_at,
                        SUM(temperature_2m_c * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS temperature_2m_c,
                        SUM(apparent_temperature_c * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS apparent_temperature_c,
                        SUM(relative_humidity_2m_pct * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS relative_humidity_2m_pct,
                        SUM(precipitation_probability_pct * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS precipitation_probability_pct,
                        SUM(precipitation_mm * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS precipitation_mm,
                        SUM(cloud_cover_pct * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS cloud_cover_pct,
                        SUM(wind_speed_10m_ms * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS wind_speed_10m_ms,
                        SUM(wind_speed_80m_ms * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS wind_speed_80m_ms,
                        SUM(wind_gusts_10m_ms * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS wind_gusts_10m_ms,
                        SUM(shortwave_radiation_wm2 * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS shortwave_radiation_wm2,
                        SUM(direct_radiation_wm2 * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS direct_radiation_wm2,
                        SUM(diffuse_radiation_wm2 * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS diffuse_radiation_wm2,
                        SUM(heating_degree_18c * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS heating_degree_18c,
                        SUM(cooling_degree_22c * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS cooling_degree_22c,
                        SUM(solar_generation_index * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS solar_generation_index,
                        SUM(wind_generation_index * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS wind_generation_index,
                        SUM(renewables_weather_index * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS renewables_weather_index,
                        SUM(load_weather_index * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS load_weather_index
                    FROM latest_hourly_forecast
                    GROUP BY country_code, country_name, forecast_time;
                    """
                )
            )

            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW price_forecast_weather_features AS
                    SELECT
                        CASE
                            WHEN country_code = 'DE' THEN 'DE_LU'
                            ELSE country_code
                        END AS market_area,
                        country_code,
                        country_name,
                        forecast_time AS delivery_start_utc,
                        retrieved_at,
                        temperature_2m_c,
                        apparent_temperature_c,
                        relative_humidity_2m_pct,
                        precipitation_probability_pct,
                        precipitation_mm,
                        cloud_cover_pct,
                        wind_speed_10m_ms,
                        wind_speed_80m_ms,
                        wind_gusts_10m_ms,
                        shortwave_radiation_wm2,
                        direct_radiation_wm2,
                        diffuse_radiation_wm2,
                        heating_degree_18c,
                        cooling_degree_22c,
                        solar_generation_index,
                        wind_generation_index,
                        renewables_weather_index,
                        load_weather_index
                    FROM latest_country_hourly_forecast;
                    """
                )
            )

    def _upsert_static_tables(self, locations: list[dict[str, Any]]) -> None:
        location_rows = []
        for location in locations:
            location_rows.append(
                {
                    "location_id": location["location_id"],
                    "name": location["name"],
                    "country_code": location["country_code"],
                    "country_name": location["country_name"],
                    "region": location["region"],
                    "location_type": location["location_type"],
                    "latitude": float(location["latitude"]),
                    "longitude": float(location["longitude"]),
                    "elevation_m": location.get("elevation_m"),
                    "aggregation_weight": float(location.get("aggregation_weight", 1.0)),
                    "enabled": bool(location.get("enabled", True)),
                }
            )

        alias_rows = [dict(alias) for alias in self.ENTSOE_COUNTRY_ALIASES]

        with self.engine.begin() as conn:
            if location_rows:
                location_stmt = insert(self.locations_table).values(location_rows)
                conn.execute(
                    location_stmt.on_conflict_do_update(
                        index_elements=["location_id"],
                        set_={
                            "name": location_stmt.excluded.name,
                            "country_code": location_stmt.excluded.country_code,
                            "country_name": location_stmt.excluded.country_name,
                            "region": location_stmt.excluded.region,
                            "location_type": location_stmt.excluded.location_type,
                            "latitude": location_stmt.excluded.latitude,
                            "longitude": location_stmt.excluded.longitude,
                            "elevation_m": location_stmt.excluded.elevation_m,
                            "aggregation_weight": location_stmt.excluded.aggregation_weight,
                            "enabled": location_stmt.excluded.enabled,
                        },
                    )
                )

            alias_stmt = insert(self.entsoe_country_aliases_table).values(alias_rows)
            conn.execute(
                alias_stmt.on_conflict_do_update(
                    index_elements=["entsoe_area_name"],
                    set_={
                        "country_code": alias_stmt.excluded.country_code,
                        "country_name": alias_stmt.excluded.country_name,
                    },
                )
            )

    def _build_request_params(self, location: dict[str, Any]) -> dict[str, Any]:
        return {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "hourly": ",".join(self.HOURLY_VARIABLES),
            "forecast_hours": self.forecast_hours,
            "past_hours": self.past_hours,
            "timezone": "GMT",
            "timeformat": "iso8601",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }

    def _weather_label(self, weather_code: Any) -> str | None:
        if weather_code is None or (isinstance(weather_code, float) and math.isnan(weather_code)):
            return None
        return self.WMO_LABELS.get(int(weather_code), "Unknown")

    def _fetch_location_forecast(
        self,
        location: dict[str, Any],
        retrieved_at: pd.Timestamp,
    ) -> tuple[pd.DataFrame, float | None]:
        response = self.session.get(
            self.SOURCE_URL,
            params=self._build_request_params(location),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        if "hourly" not in payload:
            raise ValueError(f"No hourly payload returned for location '{location['location_id']}'.")

        frame = pd.DataFrame(payload["hourly"])
        frame["forecast_time"] = pd.to_datetime(frame["time"], utc=True)
        frame["location_id"] = location["location_id"]
        frame["weather_model"] = "dwd_icon"
        frame["retrieved_at"] = retrieved_at.to_pydatetime()

        frame["weather_label"] = frame["weather_code"].apply(self._weather_label)
        frame["heating_degree_18c"] = (18.0 - frame["temperature_2m"]).clip(lower=0)
        frame["cooling_degree_22c"] = (frame["temperature_2m"] - 22.0).clip(lower=0)
        frame["solar_generation_index"] = (frame["shortwave_radiation"] / 1000.0).clip(lower=0, upper=1)
        frame["wind_generation_index"] = ((frame["wind_speed_80m"] / 12.0).clip(lower=0) ** 3).clip(upper=1)
        frame["renewables_weather_index"] = (
            0.55 * frame["wind_generation_index"] + 0.45 * frame["solar_generation_index"]
        ).clip(lower=0, upper=1)
        frame["load_weather_index"] = frame["heating_degree_18c"] + 0.75 * frame["cooling_degree_22c"]

        frame = frame.rename(
            columns={
                "temperature_2m": "temperature_2m_c",
                "apparent_temperature": "apparent_temperature_c",
                "relative_humidity_2m": "relative_humidity_2m_pct",
                "precipitation_probability": "precipitation_probability_pct",
                "precipitation": "precipitation_mm",
                "cloud_cover": "cloud_cover_pct",
                "wind_speed_10m": "wind_speed_10m_ms",
                "wind_speed_80m": "wind_speed_80m_ms",
                "wind_gusts_10m": "wind_gusts_10m_ms",
                "wind_direction_10m": "wind_direction_10m_deg",
                "shortwave_radiation": "shortwave_radiation_wm2",
                "direct_radiation": "direct_radiation_wm2",
                "diffuse_radiation": "diffuse_radiation_wm2",
            }
        )

        frame = frame[
            [
                "location_id",
                "weather_model",
                "retrieved_at",
                "forecast_time",
                "temperature_2m_c",
                "apparent_temperature_c",
                "relative_humidity_2m_pct",
                "precipitation_probability_pct",
                "precipitation_mm",
                "cloud_cover_pct",
                "wind_speed_10m_ms",
                "wind_speed_80m_ms",
                "wind_gusts_10m_ms",
                "wind_direction_10m_deg",
                "shortwave_radiation_wm2",
                "direct_radiation_wm2",
                "diffuse_radiation_wm2",
                "weather_code",
                "weather_label",
                "heating_degree_18c",
                "cooling_degree_22c",
                "solar_generation_index",
                "wind_generation_index",
                "renewables_weather_index",
                "load_weather_index",
            ]
        ]
        frame = frame.where(pd.notnull(frame), None)
        return frame, payload.get("elevation")

    def _update_location_elevation(self, location_id: str, elevation_m: float | None) -> None:
        if elevation_m is None:
            return
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE locations SET elevation_m = :elevation_m WHERE location_id = :location_id"),
                {"location_id": location_id, "elevation_m": float(elevation_m)},
            )

    def _upsert_hourly_rows(self, forecast_frame: pd.DataFrame) -> None:
        if forecast_frame.empty:
            return

        rows = forecast_frame.to_dict(orient="records")
        statement = insert(self.hourly_forecast_table).values(rows)
        updatable_columns = {
            column.name: getattr(statement.excluded, column.name)
            for column in self.hourly_forecast_table.columns
            if column.name not in {"location_id", "weather_model", "retrieved_at", "forecast_time"}
        }

        with self.engine.begin() as conn:
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=["location_id", "weather_model", "retrieved_at", "forecast_time"],
                    set_=updatable_columns,
                )
            )

    def run(self):
        retrieved_at = pd.Timestamp.now(tz="UTC").floor("min")
        locations = self._get_locations()

        self.logger.info(
            "Weather crawler started for %s locations (forecast_hours=%s, past_hours=%s).",
            len(locations),
            self.forecast_hours,
            self.past_hours,
        )
        print(
            f"Weather crawler started for {len(locations)} locations "
            f"(forecast_hours={self.forecast_hours}, past_hours={self.past_hours})."
        )

        self._prepare_schema()
        self._upsert_static_tables(locations)

        frames = []
        temporal_start = None
        temporal_end = None

        for location in locations:
            self.logger.info("Fetching weather forecast for %s", location["name"])
            try:
                frame, elevation = self._fetch_location_forecast(location, retrieved_at)
                frames.append(frame)
                self._update_location_elevation(location["location_id"], elevation)

                location_start = frame["forecast_time"].min()
                location_end = frame["forecast_time"].max()
                temporal_start = location_start if temporal_start is None else min(temporal_start, location_start)
                temporal_end = location_end if temporal_end is None else max(temporal_end, location_end)
            except Exception as exc:
                self.logger.error("Failed to fetch weather data for %s: %s", location["name"], exc)
                print(f"Failed to fetch weather data for {location['name']}: {exc}")

        if not frames:
            raise RuntimeError("Weather crawler did not receive any usable weather payloads.")

        combined_frame = pd.concat(frames, ignore_index=True)
        self._upsert_hourly_rows(combined_frame)

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": self.SOURCE_URL,
                "license": self.DOCS_URL,
                "description": (
                    "Hourly DWD ICON weather forecasts via Open-Meteo for weather-only and energy-weather dashboards."
                ),
                "contact": "https://open-meteo.com",
                "temporal_start": temporal_start.isoformat() if temporal_start is not None else None,
                "temporal_end": temporal_end.isoformat() if temporal_end is not None else None,
            }
        )

        self.logger.info("Weather crawler finished successfully with %s rows.", len(combined_frame))
        print(f"Weather crawler finished successfully with {len(combined_frame)} rows.")


def main(schema_name: str = "weather"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    crawler = WeatherForecastCrawler("weather_forecast", config)
    crawler.run()


if __name__ == "__main__":
    main()
