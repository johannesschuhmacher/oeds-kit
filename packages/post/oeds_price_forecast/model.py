# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small OEDS-native day-ahead price forecast model.

This module deliberately does not vendor the external bachelor-thesis code. The
first production shape is a conservative ridge-regression baseline with the same
kind of information set: EXAA/price lags, calendar features, load/renewable
forecasts, and weather proxies when available.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BERLIN_TZ = ZoneInfo("Europe/Berlin")
UTC_TZ = ZoneInfo("UTC")
MODEL_NAME = "oeds_ridge_exaa_weather"
MODEL_VERSION = "0.1.0"


@dataclass(frozen=True)
class PriceForecastConfig:
    market_area: str = "DE_LU"
    train_days: int = 56
    frequency: str = "15min"
    ridge_alpha: float = 25.0
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


def delivery_index_for_local_date(target_date: date, frequency: str = "15min") -> pd.DatetimeIndex:
    start_local = pd.Timestamp(target_date).tz_localize(BERLIN_TZ)
    end_local = start_local + pd.Timedelta(days=1)
    return pd.date_range(start_local, end_local, freq=frequency, inclusive="left").tz_convert(UTC_TZ)


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


def _regularize_series(
    series: pd.Series | None,
    index: pd.DatetimeIndex,
    name: str,
    limit: int = 3,
) -> pd.Series:
    clean = _as_utc_series(series, name)
    if clean.empty:
        return pd.Series(index=index, dtype=float, name=name)
    return clean.reindex(index.union(clean.index)).sort_index().ffill(limit=limit).reindex(index).rename(name)


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


def _build_base_index(price: pd.Series, target_dates: list[date], config: PriceForecastConfig) -> pd.DatetimeIndex:
    target_index = pd.DatetimeIndex([])
    for target_date in target_dates:
        target_index = target_index.union(delivery_index_for_local_date(target_date, config.frequency))

    price_index = _as_utc_series(price, "price_eur_mwh").index
    if price_index.empty:
        return target_index

    start = min(price_index.min(), target_index.min()) - pd.Timedelta(days=8)
    end = max(price_index.max(), target_index.max()) + pd.Timedelta(days=1)
    return pd.date_range(start.floor(config.frequency), end.ceil(config.frequency), freq=config.frequency, tz=UTC_TZ)


def _calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    local = index.tz_convert(BERLIN_TZ)
    hour = local.hour + local.minute / 60.0
    dayofweek = local.dayofweek
    frame = pd.DataFrame(index=index)
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    frame["dow_sin"] = np.sin(2 * np.pi * dayofweek / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * dayofweek / 7.0)
    frame["is_weekend"] = (dayofweek >= 5).astype(float)
    return frame


def build_feature_frame(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_dates: list[date],
    config: PriceForecastConfig,
) -> pd.DataFrame:
    base_index = _build_base_index(price, target_dates, config)
    y = _regularize_series(price, base_index, "y")
    exaa_series = _regularize_series(exaa, base_index, "exaa_price_eur_mwh")
    covariate_frame = _regularize_covariates(covariates, base_index)

    frame = pd.DataFrame(index=base_index)
    frame["y"] = y
    frame["exaa_price_eur_mwh"] = exaa_series

    periods_per_day = int(pd.Timedelta(days=1) / pd.Timedelta(config.frequency))
    for lag_days in (1, 2, 7):
        frame[f"price_lag_{lag_days}d"] = y.shift(periods_per_day * lag_days)

    lag_columns = [f"price_lag_{lag_days}d" for lag_days in (1, 2, 7)]
    frame["price_lag_mean"] = frame[lag_columns].mean(axis=1)
    frame["price_lag_spread"] = frame["price_lag_1d"] - frame["price_lag_7d"]

    if not covariate_frame.empty:
        for column in covariate_frame.columns:
            frame[f"cov_{column}"] = covariate_frame[column]

    frame = frame.join(_calendar_features(base_index))
    frame["local_date"] = frame.index.tz_convert(BERLIN_TZ).date
    frame["delivery_start_utc"] = frame.index
    return frame


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {"y", "local_date", "delivery_start_utc"}
    return [column for column in frame.columns if column not in excluded]


def _fit_ridge(train: pd.DataFrame, feature_columns: list[str], alpha: float) -> tuple[np.ndarray, pd.Series, pd.Series]:
    x = train[feature_columns].copy()
    medians = x.median(axis=0, skipna=True).fillna(0.0)
    x = x.fillna(medians)
    scales = x.std(axis=0).replace(0.0, 1.0).fillna(1.0)
    x_scaled = (x - medians) / scales
    design = np.column_stack([np.ones(len(x_scaled)), x_scaled.to_numpy(dtype=float)])
    y = train["y"].to_numpy(dtype=float)
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    try:
        coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    except np.linalg.LinAlgError:
        coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    return coef, medians, scales


def _predict(frame: pd.DataFrame, feature_columns: list[str], coef: np.ndarray, medians: pd.Series, scales: pd.Series) -> np.ndarray:
    x = frame[feature_columns].copy().fillna(medians)
    x_scaled = (x - medians) / scales
    design = np.column_stack([np.ones(len(x_scaled)), x_scaled.to_numpy(dtype=float)])
    return design @ coef


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


def forecast_day(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_date: date,
    config: PriceForecastConfig | None = None,
) -> ForecastResult:
    config = config or PriceForecastConfig()
    frame = build_feature_frame(price, exaa, covariates, [target_date], config)
    target_index = delivery_index_for_local_date(target_date, config.frequency)
    target = frame.loc[target_index]

    train_end = target_index.min()
    train_start = train_end - pd.Timedelta(days=config.train_days)
    train = frame[(frame.index >= train_start) & (frame.index < train_end)].dropna(subset=["y"])
    feature_columns = _feature_columns(frame)

    if len(train) < config.min_training_rows:
        raise ValueError(
            f"Insufficient training rows for price forecast: {len(train)} < {config.min_training_rows}."
        )

    coef, medians, scales = _fit_ridge(train, feature_columns, config.ridge_alpha)
    train_pred = pd.Series(_predict(train, feature_columns, coef, medians, scales), index=train.index)
    residuals = (train["y"] - train_pred).dropna()
    point_values = _predict(target, feature_columns, coef, medians, scales)
    point = pd.DataFrame(
        {
            "delivery_start_utc": target.index,
            "delivery_end_utc": list(target.index[1:]) + [target.index[-1] + pd.Timedelta(config.frequency)],
            "value_eur_mwh": point_values,
        }
    )

    quantile_rows = []
    residual_quantiles = residuals.quantile(list(config.quantiles)) if not residuals.empty else pd.Series(0.0, index=config.quantiles)
    for quantile in config.quantiles:
        values = point_values + float(residual_quantiles.loc[quantile])
        for delivery_start, delivery_end, value in zip(point["delivery_start_utc"], point["delivery_end_utc"], values, strict=True):
            quantile_rows.append(
                {
                    "delivery_start_utc": delivery_start,
                    "delivery_end_utc": delivery_end,
                    "quantile": float(quantile),
                    "value_eur_mwh": float(value),
                }
            )

    metrics = _metrics(target["y"], pd.Series(point_values, index=target.index))
    return ForecastResult(
        point_forecast=point,
        quantile_forecast=pd.DataFrame(quantile_rows),
        metrics=metrics,
        feature_columns=tuple(feature_columns),
        train_start_utc=train.index.min(),
        train_end_utc=train.index.max(),
    )


def backtest_forecast(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_dates: list[date],
    config: PriceForecastConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or PriceForecastConfig()
    forecast_frames = []
    metric_frames = []

    for target_date in target_dates:
        result = forecast_day(price, exaa, covariates, target_date, config)
        actual = _regularize_series(price, pd.DatetimeIndex(result.point_forecast["delivery_start_utc"]), "actual")
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
