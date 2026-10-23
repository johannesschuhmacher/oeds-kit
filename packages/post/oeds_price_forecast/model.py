# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared helpers of the day-ahead price forecast: configuration, input
cleaning, metrics, quantiles, backtests and the synthetic self-test series.

The forecast model itself is the upstream LEAR implementation, see
`oeds_price_forecast.upstream`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BERLIN_TZ = ZoneInfo("Europe/Berlin")
UTC_TZ = ZoneInfo("UTC")
MODEL_VERSION = "0.1.0"


@dataclass(frozen=True)
class PriceForecastConfig:
    market_area: str = "DE_LU"
    train_days: int = 56
    frequency: str = "15min"
    quantiles: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)
    min_training_rows: int = 7 * 96


@dataclass(frozen=True)
class ForecastResult:
    point_forecast: pd.DataFrame
    quantile_forecast: pd.DataFrame
    metrics: pd.DataFrame
    feature_columns: tuple[str, ...]
    train_start_utc: pd.Timestamp
    train_end_utc: pd.Timestamp


def _as_utc_series(series: pd.Series | None, name: str) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float, name=name)

    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    index = pd.DatetimeIndex(clean.index)
    if index.tz is None:
        index = index.tz_localize(UTC_TZ)
    else:
        index = index.tz_convert(UTC_TZ)
    clean.index = index
    clean = clean[~clean.index.duplicated(keep="last")]
    clean.name = name
    return clean.astype(float)


def _regularize_covariates(covariates: pd.DataFrame | None, index: pd.DatetimeIndex) -> pd.DataFrame:
    if covariates is None or covariates.empty:
        return pd.DataFrame(index=index)

    frame = covariates.copy()
    frame.index = pd.DatetimeIndex(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(UTC_TZ)
    else:
        frame.index = frame.index.tz_convert(UTC_TZ)
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    return frame.reindex(index.union(frame.index)).sort_index().ffill(limit=3).reindex(index)


def _metrics(actual: pd.Series, predicted: pd.Series) -> pd.DataFrame:
    aligned = pd.concat([actual.rename("actual"), predicted.rename("predicted")], axis=1).dropna()
    if aligned.empty:
        return pd.DataFrame(columns=["metric", "value"])

    error = aligned["predicted"] - aligned["actual"]
    values = {
        "mae_eur_mwh": float(error.abs().mean()),
        "rmse_eur_mwh": float(np.sqrt((error**2).mean())),
        "bias_eur_mwh": float(error.mean()),
        "rows": float(len(aligned)),
    }
    return pd.DataFrame([{"metric": metric, "value": value} for metric, value in values.items()])


def quantile_forecast(point: pd.DataFrame, offsets: pd.Series, quantiles: tuple[float, ...]) -> pd.DataFrame:
    """Quantile rows: the point forecast shifted by each quantile's offset, one block per quantile."""
    blocks = [
        point.assign(quantile=float(quantile), value_eur_mwh=point["value_eur_mwh"] + float(offsets.loc[quantile]))
        for quantile in quantiles
    ]
    return pd.concat(blocks, ignore_index=True)[["delivery_start_utc", "delivery_end_utc", "quantile", "value_eur_mwh"]]


def backtest_forecast(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_dates: list[date],
    config: PriceForecastConfig,
    forecast_fn: Callable[..., ForecastResult],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forecast each target date with `forecast_fn` and score it against the raw actual prices."""
    forecast_frames = []
    metric_frames = []

    for target_date in target_dates:
        result = forecast_fn(price, exaa, covariates, target_date, config)
        delivery_index = pd.DatetimeIndex(result.point_forecast["delivery_start_utc"])
        actual = _as_utc_series(price, "actual").reindex(delivery_index)
        forecast = result.point_forecast.copy()
        forecast["target_date"] = target_date
        forecast["actual_eur_mwh"] = actual.to_numpy(dtype=float)
        forecast_frames.append(forecast)

        metrics = _metrics(
            pd.Series(forecast["actual_eur_mwh"].to_numpy(dtype=float), index=forecast["delivery_start_utc"]),
            pd.Series(forecast["value_eur_mwh"].to_numpy(dtype=float), index=forecast["delivery_start_utc"]),
        )
        metrics["target_date"] = target_date
        metric_frames.append(metrics)

    forecasts = pd.concat(forecast_frames, ignore_index=True) if forecast_frames else pd.DataFrame()
    metrics = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
    if not metrics.empty:
        aggregate = metrics.groupby("metric", as_index=False)["value"].mean()
        aggregate["target_date"] = None
        metrics = pd.concat([metrics, aggregate], ignore_index=True)
    return forecasts, metrics


def generate_self_test_series(days: int = 120, end_date: date | None = None) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    end_date = end_date or pd.Timestamp.now(tz=BERLIN_TZ).date()
    start_local = pd.Timestamp(end_date).tz_localize(BERLIN_TZ) - pd.Timedelta(days=days)
    end_local = pd.Timestamp(end_date).tz_localize(BERLIN_TZ) + pd.Timedelta(days=1)
    index = pd.date_range(start_local, end_local, freq="15min", inclusive="left").tz_convert(UTC_TZ)

    local = index.tz_convert(BERLIN_TZ)
    hour = local.hour + local.minute / 60.0
    dow = local.dayofweek
    rng = np.random.default_rng(42)

    daily_shape = 30.0 + 22.0 * np.sin(2 * np.pi * (hour - 7) / 24.0)
    evening_peak = 18.0 * np.exp(-((hour - 19.0) ** 2) / 10.0)
    weekend_discount = np.where(dow >= 5, -8.0, 0.0)
    solar_index = np.clip(np.sin(np.pi * (hour - 5.5) / 14.0), 0, None)
    wind_index = 0.45 + 0.25 * np.sin(2 * np.pi * np.arange(len(index)) / (96 * 4))
    temperature = 10.0 + 8.0 * np.sin(2 * np.pi * np.arange(len(index)) / (96 * 365) - 1.0)
    noise = rng.normal(0.0, 4.0, len(index))

    price = daily_shape + evening_peak + weekend_discount - 18.0 * solar_index - 10.0 * wind_index + noise
    exaa = price + rng.normal(0.0, 5.5, len(index)) + 1.5
    load = 52000 + 8000 * np.sin(2 * np.pi * (hour - 8) / 24.0) - np.where(dow >= 5, 5000, 0)

    covariates = pd.DataFrame(
        {
            "load_mw": load,
            "wind_generation_index": wind_index,
            "solar_generation_index": solar_index,
            "temperature_2m_c": temperature,
            "shortwave_radiation_wm2": 900 * solar_index,
        },
        index=index,
    )
    return (
        pd.Series(price, index=index, name="price_eur_mwh"),
        pd.Series(exaa, index=index, name="exaa_price_eur_mwh"),
        covariates,
    )
