# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ENTSO-E Transparency Platform Web API crawler.

The FMS crawler imports package files from the ENTSO-E File Library. This
crawler intentionally uses the token-based Transparency Platform Web API for
small, fresh refresh windows that are useful for downstream forecasting jobs.
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient, EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError
from entsoe.parsers import parse_prices
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import insert

from crawler.common.kit_base import KitCrawler
from crawler.common.local_env import load_crawler_dotenv

API_BASE_URL = "https://web-api.tp.entsoe.eu/api"
BERLIN_TZ = "Europe/Berlin"
DEFAULT_COUNTRY_CODE = "DE_LU"
DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_LOOKAHEAD_DAYS = 2
DEFAULT_REQUEST_PAUSE_SECONDS = 0.5

DATASET_DAY_AHEAD_PRICES = "day_ahead_prices"
DATASET_EXAA_PRICES = "exaa_day_ahead_prices"
DATASET_LOAD_FORECAST = "load_forecast"
DATASET_WIND_SOLAR_FORECAST = "wind_solar_forecast"
ALL_DATASETS = {
    DATASET_DAY_AHEAD_PRICES,
    DATASET_EXAA_PRICES,
    DATASET_LOAD_FORECAST,
    DATASET_WIND_SOLAR_FORECAST,
}

PRICE_SEQUENCE_SDAC = 1
PRICE_SEQUENCE_EXAA = 2

PRICE_CONSTRAINT = "unique_entsoe_api_day_ahead_prices"
LOAD_CONSTRAINT = "unique_entsoe_api_load_forecasts"
WIND_SOLAR_CONSTRAINT = "unique_entsoe_api_wind_solar_forecasts"


class EntsoeApiCrawler(KitCrawler):
    """Crawler for selected ENTSO-E Web API time series."""

    def __init__(self, crawler_name: str, config: dict[str, Any]):
        load_crawler_dotenv()
        load_dotenv(override=False)
        super().__init__(crawler_name, config)

        self.metadata = MetaData(schema=self.schema_name)
        self.tables: dict[str, Table] = {}
        self._define_tables()

        api_key = self._api_key()
        self.pandas_client = EntsoePandasClient(api_key=api_key)
        self.raw_client = EntsoeRawClient(api_key=api_key)

    def _api_key(self) -> str:
        api_key = (
            os.getenv("ENTSOE_API_KEY")
            or os.getenv("ENTSOE_SECURITY_TOKEN")
            or os.getenv("ENTSOE_API")
            or self.config.get("api_key")
        )
        if not api_key:
            raise RuntimeError(
                "ENTSO-E API token is missing. Set ENTSOE_API_KEY, ENTSOE_SECURITY_TOKEN, or ENTSOE_API."
            )
        return str(api_key)

    def _define_tables(self) -> None:
        self.tables["day_ahead_prices"] = Table(
            "day_ahead_prices",
            self.metadata,
            Column("market_area", String, nullable=False),
            Column("sequence", Integer, nullable=False),
            Column("source_market", String, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("price_eur_mwh", Float),
            Column("currency", String, nullable=False),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "market_area",
                "sequence",
                "delivery_start_utc",
                name=PRICE_CONSTRAINT,
            ),
        )

        self.tables["load_forecasts"] = Table(
            "load_forecasts",
            self.metadata,
            Column("market_area", String, nullable=False),
            Column("process_type", String, nullable=False),
            Column("metric", String, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("load_mw", Float),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "market_area",
                "process_type",
                "metric",
                "delivery_start_utc",
                name=LOAD_CONSTRAINT,
            ),
        )

        self.tables["wind_solar_forecasts"] = Table(
            "wind_solar_forecasts",
            self.metadata,
            Column("market_area", String, nullable=False),
            Column("process_type", String, nullable=False),
            Column("psr_type", String, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("forecast_mw", Float),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "market_area",
                "process_type",
                "psr_type",
                "delivery_start_utc",
                name=WIND_SOLAR_CONSTRAINT,
            ),
        )

    def _ensure_tables(self) -> None:
        self.metadata.create_all(self.engine)
        statements = (
            f'CREATE INDEX IF NOT EXISTS "idx_entsoe_api_prices_delivery" '
            f'ON "{self.schema_name}"."day_ahead_prices" (delivery_start_utc)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsoe_api_load_delivery" '
            f'ON "{self.schema_name}"."load_forecasts" (delivery_start_utc)',
            f'CREATE INDEX IF NOT EXISTS "idx_entsoe_api_wind_solar_delivery" '
            f'ON "{self.schema_name}"."wind_solar_forecasts" (delivery_start_utc)',
        )
        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

    def _enabled_datasets(self) -> set[str]:
        configured = self.config.get("target_datasets")
        if configured:
            requested = {str(item) for item in configured}
            unknown = requested - ALL_DATASETS
            if unknown:
                raise ValueError(f"Unknown ENTSO-E API dataset(s): {', '.join(sorted(unknown))}")
            return requested

        enabled = set()
        if self.config.get("include_day_ahead_prices", True):
            enabled.add(DATASET_DAY_AHEAD_PRICES)
        if self.config.get("include_exaa_prices", True):
            enabled.add(DATASET_EXAA_PRICES)
        if self.config.get("include_load_forecast", True):
            enabled.add(DATASET_LOAD_FORECAST)
        if self.config.get("include_wind_solar_forecast", True):
            enabled.add(DATASET_WIND_SOLAR_FORECAST)
        return enabled

    def _country_code(self) -> str:
        return str(self.config.get("country_code", DEFAULT_COUNTRY_CODE))

    def _process_type(self) -> str:
        return str(self.config.get("process_type", "A01"))

    def _request_pause_seconds(self) -> float:
        return float(self.config.get("request_pause_seconds", DEFAULT_REQUEST_PAUSE_SECONDS))

    def _query_window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        configured_start = self.config.get("start_date")
        if configured_start:
            start = pd.Timestamp(configured_start)
            if start.tzinfo is None:
                start = start.tz_localize(BERLIN_TZ)
            else:
                start = start.tz_convert(BERLIN_TZ)
        else:
            today = pd.Timestamp.now(tz=BERLIN_TZ).normalize()
            start = today - pd.Timedelta(days=int(self.config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)))

        today = pd.Timestamp.now(tz=BERLIN_TZ).normalize()
        end = today + pd.Timedelta(days=int(self.config.get("lookahead_days", DEFAULT_LOOKAHEAD_DAYS)))
        return start, end

    @staticmethod
    def _datetime_index_utc(index: pd.Index) -> pd.DatetimeIndex:
        timestamps = pd.DatetimeIndex(index)
        if timestamps.tz is None:
            return timestamps.tz_localize("UTC")
        return timestamps.tz_convert("UTC")

    @staticmethod
    def _infer_delivery_end_utc(
        delivery_start_utc: pd.DatetimeIndex,
        fallback: pd.Timedelta = pd.Timedelta(hours=1),
    ) -> pd.DatetimeIndex:
        if delivery_start_utc.empty:
            return delivery_start_utc

        if len(delivery_start_utc) > 1:
            deltas = delivery_start_utc.to_series().diff().dropna()
            positive_deltas = deltas[deltas > pd.Timedelta(0)]
            if not positive_deltas.empty:
                fallback = positive_deltas.median()

        end_values = list(delivery_start_utc[1:])
        end_values.append(delivery_start_utc[-1] + fallback)
        return pd.DatetimeIndex(end_values)

    @staticmethod
    def _flatten_column_label(label: object) -> str:
        if isinstance(label, tuple):
            return " / ".join(str(part) for part in label if part is not None)
        return str(label)

    @classmethod
    def _price_series_to_frame(
        cls,
        series: pd.Series,
        *,
        market_area: str,
        sequence: int,
        source_market: str,
        fallback_resolution: pd.Timedelta = pd.Timedelta(hours=1),
    ) -> pd.DataFrame:
        if series.empty:
            return pd.DataFrame()

        clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
        if clean.empty:
            return pd.DataFrame()

        delivery_start = cls._datetime_index_utc(clean.index)
        delivery_end = cls._infer_delivery_end_utc(delivery_start, fallback_resolution)
        return pd.DataFrame(
            {
                "market_area": market_area,
                "sequence": sequence,
                "source_market": source_market,
                "delivery_start_utc": delivery_start,
                "delivery_end_utc": delivery_end,
                "price_eur_mwh": clean.to_numpy(dtype=float),
                "currency": "EUR",
                "download_time_utc": pd.Timestamp.now(tz="UTC"),
            }
        )

    @classmethod
    def _wide_forecast_to_frame(
        cls,
        frame: pd.DataFrame | pd.Series,
        *,
        market_area: str,
        process_type: str,
        value_column: str,
        label_column: str,
    ) -> pd.DataFrame:
        if isinstance(frame, pd.Series):
            frame = frame.to_frame(name=frame.name or "value")
        if frame.empty:
            return pd.DataFrame()

        delivery_start = cls._datetime_index_utc(frame.index)
        delivery_end = cls._infer_delivery_end_utc(delivery_start)
        base = pd.DataFrame(
            {
                "delivery_start_utc": delivery_start,
                "delivery_end_utc": delivery_end,
            },
            index=frame.index,
        )

        rows: list[pd.DataFrame] = []
        for column in frame.columns:
            label = cls._flatten_column_label(column)
            values = pd.to_numeric(frame[column], errors="coerce")
            part = base.copy()
            part["market_area"] = market_area
            part["process_type"] = process_type
            part[label_column] = label
            part[value_column] = values.to_numpy(dtype=float)
            part["download_time_utc"] = pd.Timestamp.now(tz="UTC")
            part = part.dropna(subset=[value_column])
            if not part.empty:
                rows.append(part)

        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    def _parse_exaa_price_xml(self, xml_text: str, market_area: str) -> pd.DataFrame:
        series_by_resolution = parse_prices(xml_text)
        frames = []
        resolution_fallbacks = {
            "15min": pd.Timedelta(minutes=15),
            "30min": pd.Timedelta(minutes=30),
            "60min": pd.Timedelta(hours=1),
        }
        for resolution, series in series_by_resolution.items():
            if series.empty:
                continue
            frames.append(
                self._price_series_to_frame(
                    series,
                    market_area=market_area,
                    sequence=PRICE_SEQUENCE_EXAA,
                    source_market="EXAA",
                    fallback_resolution=resolution_fallbacks.get(
                        resolution,
                        pd.Timedelta(hours=1),
                    ),
                )
            )

        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True).sort_values("delivery_start_utc")
        return combined.drop_duplicates(
            subset=["market_area", "sequence", "delivery_start_utc"],
            keep="last",
        )

    def _upsert_dataframe(self, table_name: str, frame: pd.DataFrame, constraint_name: str) -> int:
        if frame.empty:
            return 0

        table = self.tables[table_name]
        table_columns = [column.name for column in table.columns]
        records = (
            frame.reindex(columns=table_columns)
            .astype(object)
            .where(pd.notnull(frame.reindex(columns=table_columns)), None)
            .to_dict(orient="records")
        )

        stmt = insert(table).values(records)
        update_columns = {
            column.name: stmt.excluded[column.name]
            for column in table.columns
            if not column.primary_key
        }
        stmt = stmt.on_conflict_do_update(
            constraint=constraint_name,
            set_=update_columns,
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return len(records)

    def _refresh_day_ahead_prices(
        self,
        country_code: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> int:
        try:
            series = self.pandas_client.query_day_ahead_prices(country_code, start=start, end=end)
        except NoMatchingDataError:
            self.logger.warning("ENTSO-E API returned no SDAC day-ahead prices for %s", country_code)
            return 0

        frame = self._price_series_to_frame(
            series,
            market_area=country_code,
            sequence=PRICE_SEQUENCE_SDAC,
            source_market="SDAC",
        )
        return self._upsert_dataframe("day_ahead_prices", frame, PRICE_CONSTRAINT)

    def _refresh_exaa_prices(
        self,
        country_code: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> int:
        try:
            xml_text = self.raw_client.query_day_ahead_prices(
                country_code,
                start=start,
                end=end,
                sequence=PRICE_SEQUENCE_EXAA,
            )
        except NoMatchingDataError:
            self.logger.warning("ENTSO-E API returned no EXAA prices for %s", country_code)
            return 0

        frame = self._parse_exaa_price_xml(xml_text, country_code)
        return self._upsert_dataframe("day_ahead_prices", frame, PRICE_CONSTRAINT)

    def _refresh_load_forecast(
        self,
        country_code: str,
        process_type: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> int:
        try:
            source = self.pandas_client.query_load_forecast(
                country_code,
                start=start,
                end=end,
                process_type=process_type,
            )
        except NoMatchingDataError:
            self.logger.warning("ENTSO-E API returned no load forecast for %s", country_code)
            return 0

        frame = self._wide_forecast_to_frame(
            source,
            market_area=country_code,
            process_type=process_type,
            value_column="load_mw",
            label_column="metric",
        )
        return self._upsert_dataframe("load_forecasts", frame, LOAD_CONSTRAINT)

    def _refresh_wind_solar_forecast(
        self,
        country_code: str,
        process_type: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> int:
        try:
            source = self.pandas_client.query_wind_and_solar_forecast(
                country_code,
                start=start,
                end=end,
                process_type=process_type,
            )
        except NoMatchingDataError:
            self.logger.warning("ENTSO-E API returned no wind/solar forecast for %s", country_code)
            return 0

        frame = self._wide_forecast_to_frame(
            source,
            market_area=country_code,
            process_type=process_type,
            value_column="forecast_mw",
            label_column="psr_type",
        )
        return self._upsert_dataframe("wind_solar_forecasts", frame, WIND_SOLAR_CONSTRAINT)

    def _pause_between_requests(self) -> None:
        pause_seconds = self._request_pause_seconds()
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    def run(self) -> None:
        self._ensure_tables()

        country_code = self._country_code()
        process_type = self._process_type()
        start, end = self._query_window()
        enabled = self._enabled_datasets()
        total_rows = 0

        self.logger.info(
            "Starting ENTSO-E API refresh for %s from %s to %s: %s",
            country_code,
            start.isoformat(),
            end.isoformat(),
            ", ".join(sorted(enabled)),
        )

        if DATASET_DAY_AHEAD_PRICES in enabled:
            total_rows += self._refresh_day_ahead_prices(country_code, start, end)
            self._pause_between_requests()
        if DATASET_EXAA_PRICES in enabled:
            total_rows += self._refresh_exaa_prices(country_code, start, end)
            self._pause_between_requests()
        if DATASET_LOAD_FORECAST in enabled:
            total_rows += self._refresh_load_forecast(country_code, process_type, start, end)
            self._pause_between_requests()
        if DATASET_WIND_SOLAR_FORECAST in enabled:
            total_rows += self._refresh_wind_solar_forecast(country_code, process_type, start, end)

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": date.today().isoformat(),
                "data_source": API_BASE_URL,
                "license": "ENTSO-E Transparency Platform terms and conditions",
                "description": "Selected ENTSO-E Transparency Platform Web API time series.",
                "contact": "OEDS maintainers",
                "temporal_start": start.isoformat(),
                "temporal_end": end.isoformat(),
            }
        )
        self.logger.info("Finished ENTSO-E API refresh with %s upserted row(s)", total_rows)


def main(schema_name: str) -> None:
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
        "country_code": DEFAULT_COUNTRY_CODE,
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
        "lookahead_days": DEFAULT_LOOKAHEAD_DAYS,
    }
    crawler = EntsoeApiCrawler("entsoe_api", config)
    crawler.run()


if __name__ == "__main__":
    main("entsoe_api")
