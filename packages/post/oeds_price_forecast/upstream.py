# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Adapter for the upstream `da_price_forecasting` LEAR implementation.

The adapter imports the upstream package when it is installed or when a local
repository path is provided via CLI/env. It keeps OEDS storage and source-data
loading local while delegating reusable feature/model functions upstream.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from oeds_price_forecast.model import (
    BERLIN_TZ,
    MODEL_VERSION,
    ForecastResult,
    PriceForecastConfig,
    _as_utc_series,
    _metrics,
    _regularize_covariates,
)

UPSTREAM_MODEL_NAME = "upstream_lear"
UPSTREAM_MODEL_VERSION = f"da_price_forecasting:{MODEL_VERSION}"


class UpstreamBackendUnavailable(RuntimeError):
    """Raised when the upstream backend cannot be imported or used."""


@dataclass(frozen=True)
class UpstreamModules:
    engineering: object
    lear: object


def add_upstream_repo_path(repo_path: str | None) -> None:
    if not repo_path:
        return

    root = Path(repo_path).expanduser().resolve()
    src = root / "src"
    import_path = src if src.exists() else root
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))


def load_upstream_modules(repo_path: str | None = None) -> UpstreamModules:
    add_upstream_repo_path(repo_path)
    try:
        from da_price_forecasting.features import engineering
        from da_price_forecasting.models import lear
    except ImportError as exc:
        raise UpstreamBackendUnavailable(
            "The upstream da_price_forecasting package is not importable. "
            "Install it or set DA_PRICE_FORECASTING_REPO_PATH."
        ) from exc
    return UpstreamModules(engineering=engineering, lear=lear)


def _target_daily_index(target_date: date, train_days: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(target_date).tz_localize(BERLIN_TZ) - pd.Timedelta(days=train_days + 14)
    end = pd.Timestamp(target_date).tz_localize(BERLIN_TZ)
    return pd.date_range(start.normalize(), end.normalize(), freq="D", tz=BERLIN_TZ)


def _regular_quarter_frame(series: pd.Series, column: str, index: pd.DatetimeIndex) -> pd.DataFrame:
    clean = _as_utc_series(series, column).reindex(index.union(_as_utc_series(series, column).index)).sort_index()
    clean = clean.ffill(limit=3).reindex(index)
    return clean.tz_convert(BERLIN_TZ).to_frame(column)


def _build_load_features(modules: UpstreamModules, covariates: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    if covariates.empty or "load_mw" not in covariates.columns:
        return pd.DataFrame(index=_target_daily_index(index[-1].tz_convert(BERLIN_TZ).date(), 0))

    regular = _regularize_covariates(covariates[["load_mw"]], index)
    load = regular["load_mw"].tz_convert(BERLIN_TZ).to_frame("load_fc")
    return modules.engineering.build_load_features(load)


def _build_oeds_weather_feature_block(covariates: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    if covariates.empty:
        return pd.DataFrame()

    weather_columns = [
        column
        for column in covariates.columns
        if column != "load_mw" and pd.api.types.is_numeric_dtype(covariates[column])
    ]
    if not weather_columns:
        return pd.DataFrame()

    regular = _regularize_covariates(covariates[weather_columns], index)
    local = regular.tz_convert(BERLIN_TZ)
    feature_blocks = []
    work = local.copy()
    work["date_local"] = work.index.floor("D")
    work["mtu"] = work.index.hour * 4 + work.index.minute // 15

    for column in weather_columns:
        pivot = (
            work.pivot_table(index="date_local", columns="mtu", values=column, aggfunc="mean")
            .reindex(columns=range(96))
            .interpolate(axis=1, limit=4, limit_area="inside")
        )
        pivot.columns = [f"oeds_{column}_mtu_{int(mtu):02d}" for mtu in pivot.columns]
        feature_blocks.append(pivot)

    result = pd.concat(feature_blocks, axis=1) if feature_blocks else pd.DataFrame()
    result.index.name = "date"
    return result


def _build_upstream_xy(
    modules: UpstreamModules,
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_date: date,
    config: PriceForecastConfig,
    variant: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    daily_index = _target_daily_index(target_date, config.train_days)
    start = daily_index.min().tz_convert("UTC")
    end = (daily_index.max() + pd.Timedelta(days=1)).tz_convert("UTC")
    quarter_index = pd.date_range(start, end, freq=config.frequency, inclusive="left", tz="UTC")

    price_frame = _regular_quarter_frame(price, "price_da", quarter_index)
    exaa_frame = _regular_quarter_frame(exaa if exaa is not None else pd.Series(dtype=float), "price_exaa", quarter_index)

    use_exaa_only = variant == "exaa_only"
    use_exaa_vector = variant in {"exaa_only", "exaa"}
    price_features = modules.engineering.build_price_features(
        price_frame,
        df_prices_exaa_15=exaa_frame if use_exaa_vector else None,
        exaa_vector=use_exaa_vector,
        exaa_only=use_exaa_only,
        daily_index=daily_index,
    )

    covariates = covariates if covariates is not None else pd.DataFrame()
    covariate_frame = _regularize_covariates(covariates, quarter_index)
    load_features = _build_load_features(modules, covariate_frame, quarter_index)
    weather_features = _build_oeds_weather_feature_block(covariate_frame, quarter_index)
    time_features = modules.engineering.build_temporal_features(daily_index)

    blocks = [price_features, time_features]
    if not load_features.empty:
        blocks.append(load_features)
    if not weather_features.empty:
        blocks.append(weather_features)
    X = pd.concat(blocks, axis=1).reindex(daily_index)
    X = X.dropna(axis=1, how="all").ffill().bfill()

    Y = modules.engineering.build_y_matrix(price_frame, daily_index)
    return X, Y, daily_index


def _quantiles_from_residual_proxy(
    point: pd.DataFrame,
    price: pd.Series,
    exaa: pd.Series | None,
    config: PriceForecastConfig,
) -> pd.DataFrame:
    price_clean = _as_utc_series(price, "price")
    exaa_clean = _as_utc_series(exaa, "exaa") if exaa is not None else pd.Series(dtype=float)
    residuals = (price_clean - exaa_clean.reindex(price_clean.index)).dropna()
    if residuals.empty:
        residual_offsets = pd.Series(0.0, index=list(config.quantiles))
    else:
        residual_offsets = residuals.tail(config.train_days * 96).quantile(list(config.quantiles))

    rows = []
    for quantile in config.quantiles:
        offset = float(residual_offsets.loc[quantile])
        for _, row in point.iterrows():
            rows.append(
                {
                    "delivery_start_utc": row["delivery_start_utc"],
                    "delivery_end_utc": row["delivery_end_utc"],
                    "quantile": float(quantile),
                    "value_eur_mwh": float(row["value_eur_mwh"] + offset),
                }
            )
    return pd.DataFrame(rows)


def forecast_day_upstream(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_date: date,
    config: PriceForecastConfig,
    repo_path: str | None = None,
    variant: str = "exaa_only",
) -> ForecastResult:
    modules = load_upstream_modules(repo_path)
    X, Y, _ = _build_upstream_xy(modules, price, exaa, covariates, target_date, config, variant)
    forecast_day_index = pd.DatetimeIndex([pd.Timestamp(target_date).tz_localize(BERLIN_TZ)])
    train_rows = X[(X.index >= forecast_day_index[0] - pd.Timedelta(days=config.train_days)) & (X.index < forecast_day_index[0])]
    if len(train_rows) < max(7, config.min_training_rows // 96):
        raise ValueError(
            f"Insufficient upstream LEAR training days: {len(train_rows)} < {max(7, config.min_training_rows // 96)}."
        )

    forecast_df, _, _, _, _ = modules.lear.rolling_point_forecast(
        X=X,
        Y=Y,
        forecast_days=forecast_day_index,
        train_days=config.train_days,
        lars_start_date=pd.Timestamp("2100-01-01", tz=BERLIN_TZ),
    )
    if forecast_df.empty:
        raise ValueError("Upstream LEAR did not return forecast rows.")

    index_utc = forecast_df.index.tz_convert("UTC")
    point = pd.DataFrame(
        {
            "delivery_start_utc": index_utc,
            "delivery_end_utc": list(index_utc[1:]) + [index_utc[-1] + pd.Timedelta(config.frequency)],
            "value_eur_mwh": forecast_df["y_pred"].to_numpy(dtype=float),
        }
    )
    actual = pd.Series(forecast_df["y_true"].to_numpy(dtype=float), index=index_utc)
    predicted = pd.Series(forecast_df["y_pred"].to_numpy(dtype=float), index=index_utc)
    metrics = _metrics(actual, predicted)
    quantiles = _quantiles_from_residual_proxy(point, price, exaa, config)
    return ForecastResult(
        point_forecast=point,
        quantile_forecast=quantiles,
        metrics=metrics,
        feature_columns=tuple(str(column) for column in X.columns),
        train_start_utc=train_rows.index.min().tz_convert("UTC"),
        train_end_utc=train_rows.index.max().tz_convert("UTC"),
    )


def backtest_forecast_upstream(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_dates: list[date],
    config: PriceForecastConfig,
    repo_path: str | None = None,
    variant: str = "exaa_only",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    forecast_frames = []
    metric_frames = []
    for target_date in target_dates:
        result = forecast_day_upstream(price, exaa, covariates, target_date, config, repo_path, variant)
        actual = _as_utc_series(price, "actual").reindex(pd.DatetimeIndex(result.point_forecast["delivery_start_utc"]))
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
        aggregate["target_date"] = np.nan
        metrics = pd.concat([metrics, aggregate], ignore_index=True)
    return forecasts, metrics
