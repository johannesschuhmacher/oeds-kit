#!/usr/bin/env python
# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E402,I001

"""Run the OEDS day-ahead price forecast as a post-run script.

The default mode reads OEDS PostgreSQL schemas and writes derived forecasts to
`price_forecast`. `--self-test` runs the same model on deterministic synthetic
data, which keeps CI and local development independent of source credentials.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oeds_post_scripts.runtime_env import resolve_database_uri
from oeds_price_forecast.model import PriceForecastConfig, generate_self_test_series
from oeds_price_forecast.upstream import (
    UPSTREAM_MODEL_NAME,
    UPSTREAM_MODEL_VERSION,
    UpstreamBackendUnavailable,
    backtest_forecast_upstream,
    forecast_day_upstream,
)


BERLIN_TZ = ZoneInfo("Europe/Berlin")
DEFAULT_DATABASE_URI = "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path="
FORECAST_SCHEMA = "price_forecast"
PERIODS_PER_DAY = 96
API_TRAINING_BUFFER_DAYS = 7
API_MIN_TRAINING_COVERAGE_RATIO = 0.85


def _parse_target_date(raw: str | None) -> date:
    if raw:
        return pd.Timestamp(raw).date()
    return (pd.Timestamp.now(tz=BERLIN_TZ).normalize() + pd.Timedelta(days=1)).date()


def _short_sqlalchemy_error(exc: SQLAlchemyError) -> str:
    raw = str(getattr(exc, "orig", None) or exc).strip()
    first_line = raw.splitlines()[0] if raw else exc.__class__.__name__
    return first_line


def _env_default(name: str, fallback: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in {None, ""} else fallback


def _env_int(name: str, fallback: int) -> int:
    value = _env_default(name)
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _env_bool(name: str, fallback: bool) -> bool:
    value = _env_default(name)
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _delivery_bounds(target_date: date, train_days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(target_date).tz_localize(BERLIN_TZ) - pd.Timedelta(days=train_days + 14)
    end = pd.Timestamp(target_date).tz_localize(BERLIN_TZ) + pd.Timedelta(days=1)
    return start.tz_convert("UTC"), end.tz_convert("UTC")


def _market_area_alt(market_area: str) -> str:
    if market_area == "DE_LU":
        return "DE-LU"
    if market_area == "DE-LU":
        return "DE_LU"
    return market_area


def _market_area_params(market_area: str, **extra) -> dict:
    return {
        "market_area": market_area,
        "market_area_alt": _market_area_alt(market_area),
        **extra,
    }


def _existing_tables(conn) -> set[tuple[str, str]]:
    rows = conn.execute(
        text(
            """
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_schema IN ('entsoe_fms', 'entsoe_api', 'weather')
            """
        )
    )
    return {(schema, table) for schema, table in rows}


def _read_series(conn, sql: str, params: dict, value_column: str) -> pd.Series:
    return _series_from_frame(pd.read_sql_query(text(sql), conn, params=params), value_column)


def _series_from_frame(frame: pd.DataFrame, value_column: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float, name=value_column)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
    frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
    frame = frame.dropna(subset=["ts", value_column]).sort_values("ts")
    if frame.empty:
        return pd.Series(dtype=float, name=value_column)
    series = frame.groupby("ts")[value_column].last().sort_index()
    series.name = value_column
    return series


def _combine_series(name: str, *series_items: pd.Series) -> pd.Series:
    clean_items = [series.rename(name) for series in series_items if series is not None and not series.empty]
    if not clean_items:
        return pd.Series(dtype=float, name=name)
    combined = pd.concat(clean_items).sort_index()
    return combined.groupby(level=0).last().sort_index().rename(name)


def _training_history_window(target_date: date, config: PriceForecastConfig) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    training_end = pd.Timestamp(target_date).tz_localize(BERLIN_TZ).tz_convert("UTC")
    required_days = config.train_days + API_TRAINING_BUFFER_DAYS
    training_start = training_end - pd.Timedelta(days=required_days)
    return training_start, training_end, required_days


def _series_window_rows(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> int:
    if series is None or series.empty:
        return 0
    index = pd.DatetimeIndex(series.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    return int(((index >= start) & (index < end)).sum())


def _coverage_summary(
    series: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    required_rows: int,
) -> dict:
    rows = _series_window_rows(series, start, end)
    coverage_ratio = rows / required_rows if required_rows else 0.0
    return {
        "rows": rows,
        "required_rows": required_rows,
        "coverage_ratio": round(float(coverage_ratio), 4),
        "enough": coverage_ratio >= API_MIN_TRAINING_COVERAGE_RATIO,
    }


def _combine_training_fallback_series(
    name: str,
    fms: pd.Series,
    api: pd.Series,
    training_end: pd.Timestamp,
    api_training_ready: bool,
) -> pd.Series:
    if api_training_ready or fms is None or fms.empty:
        return _combine_series(name, fms, api)

    fms_history = fms[fms.index < training_end] if not fms.empty else pd.Series(dtype=float, name=name)
    fms_fresh = fms[fms.index >= training_end] if not fms.empty else pd.Series(dtype=float, name=name)
    api_fresh = api[api.index >= training_end] if api is not None and not api.empty else pd.Series(dtype=float, name=name)
    fresh = _combine_series(name, fms_fresh, api_fresh)
    return _combine_series(name, fms_history, fresh)


def _combine_covariates(*frames: pd.DataFrame) -> pd.DataFrame:
    clean_frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not clean_frames:
        return pd.DataFrame()
    combined = pd.concat(clean_frames, axis=1, sort=True).sort_index()
    result = pd.DataFrame(index=combined.index)
    for column in dict.fromkeys(combined.columns):
        candidates = combined.loc[:, combined.columns == column]
        result[column] = candidates.ffill(axis=1).iloc[:, -1]
    return result


def _load_price_series(
    conn,
    tables: set[tuple[str, str]],
    market_area: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    target_date: date,
    config: PriceForecastConfig,
) -> tuple[pd.Series, pd.Series, dict]:
    fms_sdac = pd.Series(dtype=float, name="price")
    fms_exaa = pd.Series(dtype=float, name="exaa")
    api_sdac = pd.Series(dtype=float, name="price")
    api_exaa = pd.Series(dtype=float, name="exaa")
    params = _market_area_params(market_area, start=start, end=end)

    if ("entsoe_fms", "EnergyPrices") in tables:
        # Sequence 1 (or none) is the SDAC auction, sequence 2 the EXAA auction.
        frame = pd.read_sql_query(
            text(
                """
                SELECT
                    "DateTime(UTC)" AS ts,
                    "Price[Currency/MWh]" AS price,
                    CASE WHEN TRIM(COALESCE("Sequence", '')) = '2' THEN 'EXAA' ELSE 'SDAC' END AS auction
                FROM entsoe_fms."EnergyPrices"
                WHERE "AreaDisplayName" IN (:market_area, :market_area_alt)
                  AND "AreaTypeCode" = 'BZN'
                  AND (TRIM(COALESCE("Sequence", '')) IN ('', '2') OR "Sequence" = '1')
                  AND "DateTime(UTC)" >= :start AND "DateTime(UTC)" < :end
                ORDER BY 1
                """
            ),
            conn,
            params=params,
        )
        fms_sdac = _series_from_frame(frame[frame["auction"] == "SDAC"], "price")
        fms_exaa = _series_from_frame(frame[frame["auction"] == "EXAA"], "price")

    if ("entsoe_api", "day_ahead_prices") in tables:
        frame = pd.read_sql_query(
            text(
                """
                SELECT delivery_start_utc AS ts, price_eur_mwh AS price, source_market AS auction
                FROM entsoe_api.day_ahead_prices
                WHERE market_area IN (:market_area, :market_area_alt)
                  AND source_market IN ('SDAC', 'EXAA')
                  AND delivery_start_utc >= :start AND delivery_start_utc < :end
                ORDER BY 1
                """
            ),
            conn,
            params=params,
        )
        api_sdac = _series_from_frame(frame[frame["auction"] == "SDAC"], "price")
        api_exaa = _series_from_frame(frame[frame["auction"] == "EXAA"], "price")

    history_start, training_end, required_days = _training_history_window(target_date, config)
    required_rows = required_days * PERIODS_PER_DAY
    api_price_coverage = _coverage_summary(api_sdac, history_start, training_end, required_rows)
    api_exaa_coverage = _coverage_summary(api_exaa, history_start, training_end, required_rows)
    fms_price_coverage = _coverage_summary(fms_sdac, history_start, training_end, required_rows)
    fms_exaa_coverage = _coverage_summary(fms_exaa, history_start, training_end, required_rows)
    api_training_ready = bool(api_price_coverage["enough"] and api_exaa_coverage["enough"])

    price = _combine_training_fallback_series(
        "price_eur_mwh",
        fms_sdac,
        api_sdac,
        training_end,
        api_training_ready,
    )
    exaa = _combine_training_fallback_series(
        "exaa_price_eur_mwh",
        fms_exaa,
        api_exaa,
        training_end,
        api_training_ready,
    )
    source_summary = {
        "api_training_ready": api_training_ready,
        "api_training_history_start_utc": history_start.isoformat(),
        "api_training_history_end_utc": training_end.isoformat(),
        "api_training_required_days": required_days,
        "api_training_required_rows": required_rows,
        "api_price_training_coverage": api_price_coverage,
        "api_exaa_training_coverage": api_exaa_coverage,
        "fms_price_training_coverage": fms_price_coverage,
        "fms_exaa_training_coverage": fms_exaa_coverage,
        "price_source_mode": "api_training" if api_training_ready else "fms_training_api_fresh",
    }
    return price, exaa, source_summary


def _combine_training_fallback_covariates(
    fms: pd.DataFrame,
    api: pd.DataFrame,
    training_end: pd.Timestamp,
    api_training_ready: bool,
) -> pd.DataFrame:
    if api_training_ready or fms is None or fms.empty:
        return _combine_covariates(fms, api)

    fms_history = fms[fms.index < training_end] if not fms.empty else pd.DataFrame()
    fms_fresh = fms[fms.index >= training_end] if not fms.empty else pd.DataFrame()
    api_fresh = api[api.index >= training_end] if api is not None and not api.empty else pd.DataFrame()
    return _combine_covariates(fms_history, _combine_covariates(fms_fresh, api_fresh))


def _load_entsoe_covariate_sources(
    conn,
    tables: set[tuple[str, str]],
    market_area: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fms_frames = []
    api_frames = []

    if ("entsoe_fms", "DayAheadTotalLoadForecast") in tables:
        load = _read_series(
            conn,
            """
            SELECT "DateTime(UTC)" AS ts, "TotalLoad[MW]" AS load_mw
            FROM entsoe_fms."DayAheadTotalLoadForecast"
            WHERE "AreaDisplayName" IN (:market_area, :market_area_alt)
              AND "DateTime(UTC)" >= :start AND "DateTime(UTC)" < :end
            ORDER BY 1
            """,
            _market_area_params(market_area, start=start, end=end),
            "load_mw",
        )
        if not load.empty:
            fms_frames.append(load.to_frame())

    if ("entsoe_api", "load_forecasts") in tables:
        load = _read_series(
            conn,
            """
            SELECT delivery_start_utc AS ts, load_mw
            FROM entsoe_api.load_forecasts
            WHERE market_area IN (:market_area, :market_area_alt)
              AND metric ILIKE '%forecast%'
              AND delivery_start_utc >= :start AND delivery_start_utc < :end
            ORDER BY 1
            """,
            _market_area_params(market_area, start=start, end=end),
            "load_mw",
        )
        if not load.empty:
            api_frames.append(load.to_frame())

    if ("entsoe_fms", "GenerationForecastsForWindAndSolar") in tables:
        res_frame = pd.read_sql_query(
            text(
                """
                SELECT
                    "DateTime(UTC)" AS ts,
                    SUM(CASE WHEN "ProductionType" = 'Solar' THEN COALESCE("DayAheadGenerationForecast[MW]", "CurrentGenerationForecast[MW]") ELSE 0 END) AS solar_forecast_mw,
                    SUM(CASE WHEN "ProductionType" IN ('Wind Onshore', 'Wind Offshore') THEN COALESCE("DayAheadGenerationForecast[MW]", "CurrentGenerationForecast[MW]") ELSE 0 END) AS wind_forecast_mw
                FROM entsoe_fms."GenerationForecastsForWindAndSolar"
                WHERE "AreaDisplayName" IN (:market_area, :market_area_alt)
                  AND "DateTime(UTC)" >= :start AND "DateTime(UTC)" < :end
                GROUP BY 1
                ORDER BY 1
                """
            ),
            conn,
            params=_market_area_params(market_area, start=start, end=end),
        )
        if not res_frame.empty:
            res_frame["ts"] = pd.to_datetime(res_frame["ts"], utc=True, errors="coerce")
            res_frame = res_frame.set_index("ts").apply(pd.to_numeric, errors="coerce")
            fms_frames.append(res_frame)

    if ("entsoe_api", "wind_solar_forecasts") in tables:
        api_res = pd.read_sql_query(
            text(
                """
                SELECT
                    delivery_start_utc AS ts,
                    SUM(CASE WHEN psr_type ILIKE '%solar%' THEN forecast_mw ELSE 0 END) AS solar_forecast_mw,
                    SUM(CASE WHEN psr_type ILIKE '%wind%' THEN forecast_mw ELSE 0 END) AS wind_forecast_mw
                FROM entsoe_api.wind_solar_forecasts
                WHERE market_area IN (:market_area, :market_area_alt)
                  AND delivery_start_utc >= :start AND delivery_start_utc < :end
                GROUP BY 1
                ORDER BY 1
                """
            ),
            conn,
            params=_market_area_params(market_area, start=start, end=end),
        )
        if not api_res.empty:
            api_res["ts"] = pd.to_datetime(api_res["ts"], utc=True, errors="coerce")
            api_res = api_res.set_index("ts").apply(pd.to_numeric, errors="coerce")
            api_frames.append(api_res)

    return _combine_covariates(*fms_frames), _combine_covariates(*api_frames)


def _load_entsoe_covariates(
    conn,
    tables: set[tuple[str, str]],
    market_area: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    training_end: pd.Timestamp,
    api_training_ready: bool,
) -> tuple[pd.DataFrame, dict]:
    fms_covariates, api_covariates = _load_entsoe_covariate_sources(conn, tables, market_area, start, end)
    covariates = _combine_training_fallback_covariates(
        fms_covariates,
        api_covariates,
        training_end,
        api_training_ready,
    )
    return covariates, {
        "fms_entsoe_covariate_rows": int(len(fms_covariates)),
        "api_entsoe_covariate_rows": int(len(api_covariates)),
        "entsoe_covariate_source_mode": "api_training" if api_training_ready else "fms_training_api_fresh",
    }


def _load_weather_covariates(
    conn,
    tables: set[tuple[str, str]],
    market_area: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if ("weather", "price_forecast_weather_features") in tables:
        frame = pd.read_sql_query(
            text(
                """
                SELECT *
                FROM weather.price_forecast_weather_features
                WHERE market_area = :market_area
                  AND delivery_start_utc >= :start AND delivery_start_utc < :end
                ORDER BY delivery_start_utc
                """
            ),
            conn,
            params={"market_area": market_area, "start": start, "end": end},
        )
    elif ("weather", "latest_country_hourly_forecast") in tables:
        country_code = "DE" if market_area in {"DE_LU", "DE-LU"} else market_area[:2]
        frame = pd.read_sql_query(
            text(
                """
                SELECT
                    forecast_time AS delivery_start_utc,
                    temperature_2m_c,
                    wind_speed_80m_ms,
                    shortwave_radiation_wm2,
                    solar_generation_index,
                    wind_generation_index,
                    renewables_weather_index,
                    load_weather_index
                FROM weather.latest_country_hourly_forecast
                WHERE country_code = :country_code
                  AND forecast_time >= :start AND forecast_time < :end
                ORDER BY forecast_time
                """
            ),
            conn,
            params={"country_code": country_code, "start": start, "end": end},
        )
    else:
        return pd.DataFrame()

    if frame.empty:
        return pd.DataFrame()

    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["delivery_start_utc"]).set_index("delivery_start_utc")
    ignored = {"market_area", "country_code", "country_name", "retrieved_at"}
    columns = [column for column in frame.columns if column not in ignored]
    return frame[columns].apply(pd.to_numeric, errors="coerce")


def load_oeds_inputs(
    engine,
    market_area: str,
    target_date: date,
    config: PriceForecastConfig,
) -> tuple[pd.Series, pd.Series, pd.DataFrame, dict]:
    start, end = _delivery_bounds(target_date, config.train_days)
    _, training_end, _ = _training_history_window(target_date, config)
    with engine.connect() as conn:
        tables = _existing_tables(conn)
        price, exaa, price_source_summary = _load_price_series(conn, tables, market_area, start, end, target_date, config)
        entsoe_covariates, entsoe_covariate_summary = _load_entsoe_covariates(
            conn,
            tables,
            market_area,
            start,
            end,
            training_end,
            bool(price_source_summary["api_training_ready"]),
        )
        weather_covariates = _load_weather_covariates(conn, tables, market_area, start, end)
    covariates = _combine_covariates(entsoe_covariates, weather_covariates)
    summary = {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "price_rows": int(len(price)),
        "exaa_rows": int(len(exaa)),
        "covariate_rows": int(len(covariates)),
        "covariate_columns": list(covariates.columns),
    } | price_source_summary | entsoe_covariate_summary
    return price, exaa, covariates, summary


def ensure_forecast_schema(engine, schema: str = FORECAST_SCHEMA) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}".forecast_runs (
                    run_id text PRIMARY KEY,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    target_date date NOT NULL,
                    market_area text NOT NULL,
                    model_name text NOT NULL,
                    model_version text NOT NULL,
                    variant text NOT NULL,
                    status text NOT NULL,
                    message text,
                    train_start_utc timestamptz,
                    train_end_utc timestamptz,
                    config_json text NOT NULL,
                    source_summary_json text NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}".point_forecasts (
                    run_id text NOT NULL REFERENCES "{schema}".forecast_runs(run_id) ON DELETE CASCADE,
                    market_area text NOT NULL,
                    delivery_start_utc timestamptz NOT NULL,
                    delivery_end_utc timestamptz NOT NULL,
                    value_eur_mwh double precision NOT NULL,
                    PRIMARY KEY (run_id, delivery_start_utc)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}".quantile_forecasts (
                    run_id text NOT NULL REFERENCES "{schema}".forecast_runs(run_id) ON DELETE CASCADE,
                    market_area text NOT NULL,
                    delivery_start_utc timestamptz NOT NULL,
                    delivery_end_utc timestamptz NOT NULL,
                    quantile double precision NOT NULL,
                    value_eur_mwh double precision NOT NULL,
                    PRIMARY KEY (run_id, delivery_start_utc, quantile)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}".metrics (
                    run_id text NOT NULL REFERENCES "{schema}".forecast_runs(run_id) ON DELETE CASCADE,
                    target_date date,
                    metric text NOT NULL,
                    value double precision NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS idx_price_forecast_runs_latest
                ON "{schema}".forecast_runs (market_area, variant, status, created_at DESC)
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS idx_price_forecast_runs_target
                ON "{schema}".forecast_runs (market_area, target_date, variant, status)
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS idx_price_forecast_point_delivery
                ON "{schema}".point_forecasts (market_area, delivery_start_utc)
                """
            )
        )
        conn.execute(text("NOTIFY pgrst, 'reload schema'"))


def write_run(
    engine,
    run_id: str,
    target_date: date,
    market_area: str,
    variant: str,
    status: str,
    config: PriceForecastConfig,
    source_summary: dict,
    message: str | None = None,
    train_start_utc: pd.Timestamp | None = None,
    train_end_utc: pd.Timestamp | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO "{FORECAST_SCHEMA}".forecast_runs (
                    run_id, target_date, market_area, model_name, model_version,
                    variant, status, message, train_start_utc, train_end_utc,
                    config_json, source_summary_json
                )
                VALUES (
                    :run_id, :target_date, :market_area, :model_name, :model_version,
                    :variant, :status, :message, :train_start_utc, :train_end_utc,
                    :config_json, :source_summary_json
                )
                """
            ),
            {
                "run_id": run_id,
                "target_date": target_date,
                "market_area": market_area,
                "model_name": UPSTREAM_MODEL_NAME,
                "model_version": UPSTREAM_MODEL_VERSION,
                "variant": variant,
                "status": status,
                "message": message,
                "train_start_utc": train_start_utc,
                "train_end_utc": train_end_utc,
                "config_json": json.dumps(config.__dict__, default=str, sort_keys=True),
                "source_summary_json": json.dumps(source_summary, default=str, sort_keys=True),
            },
        )


def mark_previous_runs_superseded(
    engine,
    run_id: str,
    market_area: str,
    target_date: date,
    variant: str,
) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                UPDATE "{FORECAST_SCHEMA}".forecast_runs
                SET
                    status = 'superseded',
                    message = COALESCE(message, 'Superseded by newer run ' || :run_id)
                WHERE market_area = :market_area
                  AND target_date = :target_date
                  AND variant = :variant
                  AND status = 'completed'
                  AND run_id <> :run_id
                """
            ),
            {
                "run_id": run_id,
                "market_area": market_area,
                "target_date": target_date,
                "variant": variant,
            },
        )
        return int(result.rowcount or 0)


def update_run_status(engine, run_id: str, status: str, message: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE "{FORECAST_SCHEMA}".forecast_runs
                SET
                    status = :status,
                    message = COALESCE(:message, message)
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id, "status": status, "message": message},
        )


def cleanup_old_runs(engine, retention_days: int) -> int:
    if retention_days <= 0:
        return 0

    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    f"""
                    WITH deleted AS (
                        DELETE FROM "{FORECAST_SCHEMA}".forecast_runs
                        WHERE created_at < now() - (:retention_days * INTERVAL '1 day')
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM deleted
                    """
                ),
                {"retention_days": retention_days},
            ).scalar()
            or 0
        )


def write_forecast_result(engine, run_id: str, market_area: str, result, target_date: date) -> None:
    point = result.point_forecast.copy()
    point["run_id"] = run_id
    point["market_area"] = market_area
    point[["run_id", "market_area", "delivery_start_utc", "delivery_end_utc", "value_eur_mwh"]].to_sql(
        "point_forecasts",
        engine,
        schema=FORECAST_SCHEMA,
        if_exists="append",
        index=False,
    )

    quantiles = result.quantile_forecast.copy()
    quantiles["run_id"] = run_id
    quantiles["market_area"] = market_area
    quantiles[["run_id", "market_area", "delivery_start_utc", "delivery_end_utc", "quantile", "value_eur_mwh"]].to_sql(
        "quantile_forecasts",
        engine,
        schema=FORECAST_SCHEMA,
        if_exists="append",
        index=False,
    )

    if not result.metrics.empty:
        metrics = result.metrics.copy()
        metrics["run_id"] = run_id
        metrics["target_date"] = target_date
        metrics[["run_id", "target_date", "metric", "value"]].to_sql(
            "metrics",
            engine,
            schema=FORECAST_SCHEMA,
            if_exists="append",
            index=False,
        )


def _backtest_dates(target_date: date, days: int) -> list[date]:
    if days <= 0:
        return []
    end = pd.Timestamp(target_date) - pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=days - 1)
    return [stamp.date() for stamp in pd.date_range(start, end, freq="D")]


def run_self_test(args: argparse.Namespace) -> int:
    config = PriceForecastConfig(
        market_area=args.market_area,
        train_days=args.train_days,
    )
    target_date = _parse_target_date(args.target_date)
    price, exaa, covariates = generate_self_test_series(days=max(args.train_days + args.backtest_days + 20, 120), end_date=target_date)
    result = forecast_day_upstream(price, exaa, covariates, target_date, config, variant=args.upstream_variant)
    print(f"Self-test forecast rows: {len(result.point_forecast)}")
    print(result.metrics.to_string(index=False))

    dates = _backtest_dates(target_date, args.backtest_days)
    if dates:
        _, metrics = backtest_forecast_upstream(price, exaa, covariates, dates, config, variant=args.upstream_variant)
        aggregate = metrics[metrics["target_date"].isna()] if "target_date" in metrics.columns else metrics
        print("Self-test backtest aggregate:")
        print(aggregate.to_string(index=False))
    return 0


def run_db_forecast(args: argparse.Namespace) -> int:
    target_date = _parse_target_date(args.target_date)
    config = PriceForecastConfig(
        market_area=args.market_area,
        train_days=args.train_days,
    )
    engine = create_engine(resolve_database_uri(args.database_uri))
    try:
        ensure_forecast_schema(engine)
        price, exaa, covariates, source_summary = load_oeds_inputs(engine, args.market_area, target_date, config)
    except SQLAlchemyError as exc:
        print(f"Price forecast could not connect to the OEDS database: {_short_sqlalchemy_error(exc)}", file=sys.stderr)
        return 2
    run_id = str(uuid.uuid4())

    try:
        result = forecast_day_upstream(price, exaa, covariates, target_date, config, variant=args.upstream_variant)
    except UpstreamBackendUnavailable as exc:
        write_run(
            engine,
            run_id,
            target_date,
            args.market_area,
            "day_ahead",
            "failed",
            config,
            source_summary,
            message=str(exc),
        )
        print(f"Price forecast failed: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        write_run(
            engine,
            run_id,
            target_date,
            args.market_area,
            "day_ahead",
            "skipped",
            config,
            source_summary,
            message=str(exc),
        )
        print(f"Price forecast skipped: {exc}")
        return 0 if args.skip_if_insufficient_data else 1

    source_summary = source_summary | {"upstream_variant": args.upstream_variant}
    write_run(
        engine,
        run_id,
        target_date,
        args.market_area,
        "day_ahead",
        "writing",
        config,
        source_summary,
        train_start_utc=result.train_start_utc,
        train_end_utc=result.train_end_utc,
    )
    try:
        write_forecast_result(engine, run_id, args.market_area, result, target_date)
    except Exception as exc:
        update_run_status(engine, run_id, "failed", str(exc))
        raise
    update_run_status(engine, run_id, "completed")
    superseded_count = mark_previous_runs_superseded(engine, run_id, args.market_area, target_date, "day_ahead")
    print(f"Price forecast written: run_id={run_id}, rows={len(result.point_forecast)}")
    if superseded_count:
        print(f"Superseded previous day-ahead forecast runs: {superseded_count}")

    dates = _backtest_dates(target_date, args.backtest_days)
    if dates:
        backtest_run_id = str(uuid.uuid4())
        _, metrics = backtest_forecast_upstream(price, exaa, covariates, dates, config, variant=args.upstream_variant)
        write_run(
            engine,
            backtest_run_id,
            target_date,
            args.market_area,
            "backtest",
            "writing",
            config,
            source_summary | {"backtest_days": args.backtest_days},
        )
        metrics = metrics.copy()
        metrics["run_id"] = backtest_run_id
        try:
            metrics[["run_id", "target_date", "metric", "value"]].to_sql(
                "metrics",
                engine,
                schema=FORECAST_SCHEMA,
                if_exists="append",
                index=False,
            )
        except Exception as exc:
            update_run_status(engine, backtest_run_id, "failed", str(exc))
            raise
        update_run_status(engine, backtest_run_id, "completed")
        backtest_superseded_count = mark_previous_runs_superseded(
            engine,
            backtest_run_id,
            args.market_area,
            target_date,
            "backtest",
        )
        print(f"Backtest metrics written: run_id={backtest_run_id}, days={args.backtest_days}")
        if backtest_superseded_count:
            print(f"Superseded previous backtest runs: {backtest_superseded_count}")

    deleted_count = cleanup_old_runs(engine, args.retention_days)
    if deleted_count:
        print(f"Deleted old price forecast runs beyond retention: {deleted_count}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OEDS day-ahead price forecast.")
    parser.add_argument("--database-uri", default=_env_default("OEDS_PRICE_FORECAST_DATABASE_URI", DEFAULT_DATABASE_URI))
    parser.add_argument("--market-area", default=_env_default("OEDS_PRICE_FORECAST_MARKET_AREA", "DE_LU"))
    parser.add_argument("--target-date")
    parser.add_argument("--train-days", type=int, default=_env_int("OEDS_PRICE_FORECAST_TRAIN_DAYS", 56))
    parser.add_argument("--backtest-days", type=int, default=_env_int("OEDS_PRICE_FORECAST_BACKTEST_DAYS", 0))
    parser.add_argument("--retention-days", type=int, default=_env_int("OEDS_PRICE_FORECAST_RETENTION_DAYS", 180))
    parser.add_argument(
        "--upstream-variant",
        choices=["exaa_only", "exaa"],
        default=_env_default("OEDS_PRICE_FORECAST_UPSTREAM_VARIANT", "exaa_only"),
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--skip-if-insufficient-data",
        dest="skip_if_insufficient_data",
        action="store_true",
        default=_env_bool("OEDS_PRICE_FORECAST_SKIP_IF_INSUFFICIENT_DATA", True),
    )
    parser.add_argument(
        "--fail-if-insufficient-data",
        dest="skip_if_insufficient_data",
        action="store_false",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test(args)
    return run_db_forecast(args)


if __name__ == "__main__":
    sys.exit(main())
