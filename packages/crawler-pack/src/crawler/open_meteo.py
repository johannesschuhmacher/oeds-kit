# SPDX-FileCopyrightText: OpenData Developers
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
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

from crawler.common.crawler_utils import build_session, config_or_env, copy_upsert, has_credential
from crawler.common.kit_base import KitCrawler

GRID_FILE = Path(__file__).resolve().parent / "data" / "open_meteo_grid.json"


class OpenMeteoLimitReached(Exception):
    """Open-Meteo answered 429: a minutely, hourly or daily call limit is used up."""


class OpenMeteoCrawler(KitCrawler):
    """Hourly DWD ICON forecasts from Open-Meteo on a 1-degree grid over Europe.

    The grid (crawler/data/open_meteo_grid.json, made by deploy/tools/make_open_meteo_grid.py)
    holds the land points of the ENTSO-E countries. Each run stores the new forecast;
    afterwards only the newest run and the first run of each UTC day are kept.
    """

    SOURCE_URL = "https://api.open-meteo.com/v1/dwd-icon"
    CUSTOMER_URL = "https://customer-api.open-meteo.com/v1/dwd-icon"
    DOCS_URL = "https://open-meteo.com/en/docs/dwd-api"

    # 15 variables: Open-Meteo counts a request with more than 10 variables as
    # (variables / 10) calls per location.
    HOURLY_VARIABLES = {
        "temperature_2m": "temperature_2m_c",
        "apparent_temperature": "apparent_temperature_c",
        "relative_humidity_2m": "relative_humidity_2m_pct",
        "precipitation_probability": "precipitation_probability_pct",
        "precipitation": "precipitation_mm",
        "cloud_cover": "cloud_cover_pct",
        "wind_speed_10m": "wind_speed_10m_ms",
        "wind_speed_80m": "wind_speed_80m_ms",
        "wind_speed_120m": "wind_speed_120m_ms",
        "wind_gusts_10m": "wind_gusts_10m_ms",
        "wind_direction_10m": "wind_direction_10m_deg",
        "shortwave_radiation": "shortwave_radiation_wm2",
        "direct_radiation": "direct_radiation_wm2",
        "diffuse_radiation": "diffuse_radiation_wm2",
        "weather_code": "weather_code",
    }

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
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with hail",
    }

    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self.metadata = MetaData(schema=self.schema_name)
        # Open-Meteo answers 503 "The service is overloaded" at times: retry at once,
        # then after 20, 40, 80 and 120 s. 429 is not retried: after the daily limit
        # Open-Meteo sends a Retry-After until midnight, and urllib3 slept that long
        # (2026-11-13: runs hung from 12:45 until 00:03 and blocked the later runs).
        self.session = build_session(
            self.config.get("user_agent"), retries=5, backoff_factor=10, retry_statuses=(500, 502, 503, 504, 599)
        )
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))
        self.forecast_hours = int(self.config.get("forecast_hours", 120))
        self.past_hours = int(self.config.get("past_hours", 24))
        self.batch_size = int(self.config.get("batch_size", 50))
        # The free API allows 600 calls per minute; stay below it.
        self.calls_per_minute = float(self.config.get("calls_per_minute", 500))
        api_key = config_or_env(self.config, "api_key", "OPEN_METEO_API_KEY")
        self.api_key = str(api_key) if has_credential(api_key) else None

        self.locations_table = Table(
            "locations",
            self.metadata,
            Column("location_id", String, primary_key=True),
            Column("name", String, nullable=False),
            Column("country_code", String, nullable=False),
            Column("country_name", String, nullable=False),
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

        self.runs_table = Table(
            "runs",
            self.metadata,
            Column("retrieved_at", DateTime(timezone=True), primary_key=True),
            Column("locations", Integer, nullable=False),
            Column("rows", Integer, nullable=False),
        )

        self.hourly_forecast_table = Table(
            "hourly_forecast",
            self.metadata,
            Column("location_id", String, nullable=False, primary_key=True),
            Column("weather_model", String, nullable=False, primary_key=True),
            Column("retrieved_at", DateTime(timezone=True), nullable=False, primary_key=True),
            Column("forecast_time", DateTime(timezone=True), nullable=False, primary_key=True),
            *[Column(name, Integer if name == "weather_code" else Float) for name in self.HOURLY_VARIABLES.values()],
            Column("weather_label", String),
            Column("heating_degree_18c", Float),
            Column("cooling_degree_22c", Float),
            Column("solar_generation_index", Float),
            Column("wind_generation_index", Float),
            Column("renewables_weather_index", Float),
            Column("load_weather_index", Float),
        )

    def _get_locations(self) -> list[dict[str, Any]]:
        """The configured ``locations`` or the grid; the weight of a grid point is its cell area (cos latitude)."""
        if "locations" in self.config:
            locations = [dict(location) for location in self.config["locations"] if location.get("enabled", True)]
        else:
            grid = json.loads(GRID_FILE.read_text(encoding="utf-8"))
            locations = [
                {
                    "location_id": f"{country.lower()}_{lat:g}_{lon:g}",
                    "name": f"{abs(lat):g}°{'N' if lat >= 0 else 'S'} {abs(lon):g}°{'E' if lon >= 0 else 'W'}",
                    "country_code": country,
                    "country_name": grid["countries"][country],
                    "latitude": lat,
                    "longitude": lon,
                    "aggregation_weight": round(math.cos(math.radians(lat)), 4),
                }
                for country, lat, lon in grid["points"]
            ]
        for location in locations:
            location.setdefault("aggregation_weight", 1.0)
            location["enabled"] = True
        if not locations:
            raise ValueError("At least one weather location must be enabled.")
        return locations

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            # Until release 1.4.0, open_meteo stored one row per variable (column
            # "variable") for five locations; its tables are replaced.
            old_layout = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'hourly_forecast' AND column_name = 'variable'"
                ),
                {"schema": self.schema_name},
            ).first()
            if old_layout:
                self.logger.info("Replacing the tables of the previous open_meteo crawler.")
                for name in ("hourly_forecast", "locations", "access_status"):
                    conn.execute(text(f'DROP TABLE IF EXISTS "{self.schema_name}"."{name}" CASCADE'))

        self.metadata.create_all(
            self.engine,
            tables=[self.locations_table, self.entsoe_country_aliases_table, self.runs_table, self.hourly_forecast_table],
        )

        value_columns = list(self.HOURLY_VARIABLES.values()) + [
            "weather_label",
            "heating_degree_18c",
            "cooling_degree_22c",
            "solar_generation_index",
            "wind_generation_index",
            "renewables_weather_index",
            "load_weather_index",
        ]
        averaged = [column for column in value_columns if column not in {"weather_code", "weather_label", "wind_direction_10m_deg"}]
        average = ",\n".join(
            f"SUM({column} * aggregation_weight) / NULLIF(SUM(aggregation_weight), 0) AS {column}" for column in averaged
        )
        # The columns of the former weather.price_forecast_weather_features.
        price_features = [
            "temperature_2m_c",
            "apparent_temperature_c",
            "relative_humidity_2m_pct",
            "precipitation_probability_pct",
            "precipitation_mm",
            "cloud_cover_pct",
            "wind_speed_10m_ms",
            "wind_speed_80m_ms",
            "wind_gusts_10m_ms",
            "shortwave_radiation_wm2",
            "direct_radiation_wm2",
            "diffuse_radiation_wm2",
            "heating_degree_18c",
            "cooling_degree_22c",
            "solar_generation_index",
            "wind_generation_index",
            "renewables_weather_index",
            "load_weather_index",
        ]

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "SELECT public.create_hypertable('hourly_forecast', 'forecast_time', if_not_exists => TRUE, migrate_data => TRUE);"
                    )
                )
        except Exception as exc:
            self.logger.warning(f"Could not create hypertable for hourly_forecast: {exc}")

        with self.engine.begin() as conn:
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_hourly_forecast_location_time ON hourly_forecast (location_id, forecast_time DESC);")
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hourly_forecast_retrieved ON hourly_forecast (retrieved_at DESC);"))

            for view in ("price_forecast_weather_features", "latest_country_hourly_forecast", "latest_hourly_forecast"):
                conn.execute(text(f"DROP VIEW IF EXISTS {view}"))
            conn.execute(
                text(
                    f"""
                    CREATE VIEW latest_hourly_forecast AS
                    SELECT hf.location_id, l.name AS location_name, l.country_code, l.country_name,
                           l.latitude, l.longitude, l.elevation_m, l.aggregation_weight,
                           hf.weather_model, hf.retrieved_at, hf.forecast_time,
                           {", ".join("hf." + column for column in value_columns)}
                    FROM hourly_forecast hf
                    JOIN locations l ON l.location_id = hf.location_id
                    WHERE l.enabled AND hf.retrieved_at = (SELECT MAX(retrieved_at) FROM runs);
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    CREATE VIEW latest_country_hourly_forecast AS
                    SELECT country_code, country_name, forecast_time, MAX(retrieved_at) AS retrieved_at,
                           COUNT(*) AS locations,
                           {average}
                    FROM latest_hourly_forecast
                    GROUP BY country_code, country_name, forecast_time;
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    CREATE VIEW price_forecast_weather_features AS
                    SELECT CASE WHEN country_code = 'DE' THEN 'DE_LU' ELSE country_code END AS market_area,
                           country_code, country_name, forecast_time AS delivery_start_utc, retrieved_at,
                           {", ".join(price_features)}
                    FROM latest_country_hourly_forecast;
                    """
                )
            )

    def _upsert_static_tables(self, locations: list[dict[str, Any]]) -> None:
        columns = [column.name for column in self.locations_table.columns if column.name != "elevation_m"]
        rows = [{column: location.get(column) for column in columns} for location in locations]
        with self.engine.begin() as conn:
            # Points no longer in the grid or configuration stay stored but disabled.
            conn.execute(self.locations_table.update().values(enabled=False))
            statement = insert(self.locations_table).values(rows)
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=["location_id"],
                    set_={column: getattr(statement.excluded, column) for column in columns if column != "location_id"},
                )
            )
            aliases = insert(self.entsoe_country_aliases_table).values(self.ENTSOE_COUNTRY_ALIASES)
            conn.execute(
                aliases.on_conflict_do_update(
                    index_elements=["entsoe_area_name"],
                    set_={"country_code": aliases.excluded.country_code, "country_name": aliases.excluded.country_name},
                )
            )

    def _request_params(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        params = {
            "latitude": ",".join(str(location["latitude"]) for location in batch),
            "longitude": ",".join(str(location["longitude"]) for location in batch),
            "hourly": ",".join(self.HOURLY_VARIABLES),
            "forecast_hours": self.forecast_hours,
            "past_hours": self.past_hours,
            "timezone": "GMT",
            "timeformat": "iso8601",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }
        if self.api_key:
            params["apikey"] = self.api_key
        return params

    def _weather_label(self, weather_code: Any) -> str | None:
        if weather_code is None or (isinstance(weather_code, float) and math.isnan(weather_code)):
            return None
        return self.WMO_LABELS.get(int(weather_code), "Unknown")

    def _fetch_batch(self, batch: list[dict[str, Any]], retrieved_at: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, float]]:
        response = self.session.get(
            self.CUSTOMER_URL if self.api_key else self.SOURCE_URL,
            params=self._request_params(batch),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 429:
            raise OpenMeteoLimitReached(response.text[:300])
        response.raise_for_status()
        payload = response.json()
        # One location returns an object, several a list in request order.
        payloads = payload if isinstance(payload, list) else [payload]
        if len(payloads) != len(batch):
            raise ValueError(f"Open-Meteo returned {len(payloads)} locations for {len(batch)} requested.")

        frames, elevations = [], {}
        for location, item in zip(batch, payloads):
            if "hourly" not in item:
                raise ValueError(f"No hourly payload returned for location '{location['location_id']}'.")
            frame = pd.DataFrame(item["hourly"])
            frame["forecast_time"] = pd.to_datetime(frame.pop("time"), utc=True)
            frame["location_id"] = location["location_id"]
            frames.append(frame)
            if item.get("elevation") is not None:
                elevations[location["location_id"]] = float(item["elevation"])

        frame = pd.concat(frames, ignore_index=True).rename(columns=self.HOURLY_VARIABLES)
        frame["weather_model"] = "dwd_icon"
        frame["retrieved_at"] = retrieved_at
        frame["weather_label"] = frame["weather_code"].apply(self._weather_label)
        frame["heating_degree_18c"] = (18.0 - frame["temperature_2m_c"]).clip(lower=0)
        frame["cooling_degree_22c"] = (frame["temperature_2m_c"] - 22.0).clip(lower=0)
        frame["solar_generation_index"] = (frame["shortwave_radiation_wm2"] / 1000.0).clip(lower=0, upper=1)
        frame["wind_generation_index"] = ((frame["wind_speed_80m_ms"] / 12.0).clip(lower=0) ** 3).clip(upper=1)
        frame["renewables_weather_index"] = (
            0.55 * frame["wind_generation_index"] + 0.45 * frame["solar_generation_index"]
        ).clip(lower=0, upper=1)
        frame["load_weather_index"] = frame["heating_degree_18c"] + 0.75 * frame["cooling_degree_22c"]
        return frame, elevations

    def _update_elevations(self, elevations: dict[str, float]) -> None:
        if not elevations:
            return
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE locations SET elevation_m = :elevation_m WHERE location_id = :location_id"),
                [{"location_id": key, "elevation_m": value} for key, value in elevations.items()],
            )

    def _prune_runs(self, retrieved_at: pd.Timestamp) -> None:
        """Keep the newest run and the first run of each UTC day; delete the forecasts of all other runs."""
        with self.engine.begin() as conn:
            dropped = conn.execute(
                text(
                    """
                    DELETE FROM runs r
                    WHERE r.retrieved_at < :current
                      AND r.retrieved_at > (SELECT MIN(f.retrieved_at) FROM runs f
                                            WHERE f.retrieved_at >= date_trunc('day', r.retrieved_at, 'UTC'))
                    RETURNING r.retrieved_at
                    """
                ),
                {"current": retrieved_at.to_pydatetime()},
            ).scalars().all()
            if dropped:
                conn.execute(text("DELETE FROM hourly_forecast WHERE retrieved_at = ANY(:dropped)"), {"dropped": dropped})

    def run(self):
        retrieved_at = pd.Timestamp.now(tz="UTC").floor("min")
        locations = self._get_locations()
        batches = [locations[i : i + self.batch_size] for i in range(0, len(locations), self.batch_size)]
        calls_per_location = max(1.0, len(self.HOURLY_VARIABLES) / 10)
        self.logger.info(
            "Open-Meteo crawler started for %s locations in %s requests (forecast_hours=%s, past_hours=%s).",
            len(locations),
            len(batches),
            self.forecast_hours,
            self.past_hours,
        )

        self._prepare_schema()
        self._upsert_static_tables(locations)

        frames, elevations, failed = [], {}, 0
        for index, batch in enumerate(batches):
            started = time.monotonic()
            try:
                frame, batch_elevations = self._fetch_batch(batch, retrieved_at)
                frames.append(frame)
                elevations.update(batch_elevations)
            except OpenMeteoLimitReached as exc:
                # The remaining batches would get the same answer.
                skipped = sum(len(rest) for rest in batches[index:])
                failed += skipped
                self.logger.error("Open-Meteo call limit reached, %s locations not fetched: %s", skipped, exc)
                break
            except Exception as exc:
                failed += len(batch)
                self.logger.error("Failed to fetch %s locations from %s: %s", len(batch), batch[0]["location_id"], exc)
            # Spread the calls so that the per-minute limit holds.
            pause = len(batch) * calls_per_location * 60 / self.calls_per_minute - (time.monotonic() - started)
            if pause > 0 and batch is not batches[-1]:
                time.sleep(pause)

        if not frames:
            raise RuntimeError("Open-Meteo crawler did not receive any usable weather payloads.")

        combined = pd.concat(frames, ignore_index=True)
        copy_upsert(
            self.engine,
            self.hourly_forecast_table,
            combined,
            "hourly_forecast_pkey",
            ["location_id", "weather_model", "retrieved_at", "forecast_time"],
        )
        self._update_elevations(elevations)
        with self.engine.begin() as conn:
            conn.execute(
                insert(self.runs_table)
                .values(retrieved_at=retrieved_at.to_pydatetime(), locations=len(locations) - failed, rows=len(combined))
                .on_conflict_do_nothing()
            )
        self._prune_runs(retrieved_at)

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": self.SOURCE_URL,
                "license": "CC BY 4.0 (https://open-meteo.com/en/license)",
                "description": "Hourly DWD ICON weather forecasts via Open-Meteo on a 1-degree grid over Europe.",
                "contact": "https://open-meteo.com",
                "temporal_start": combined["forecast_time"].min().isoformat(),
                "temporal_end": combined["forecast_time"].max().isoformat(),
            }
        )
        self.logger.info(
            "Open-Meteo crawler finished with %s rows for %s locations (%s failed).",
            len(combined),
            len(locations) - failed,
            failed,
        )
        if failed:
            self.logger.warning("%s of %s locations returned no data in this run.", failed, len(locations))
