# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Adapter for the upstream `da_price_forecasting` LEAR implementation.

The upstream package is the pinned `price-forecast` extra of oeds-post-scripts.
The adapter keeps OEDS storage and source-data loading local while delegating
reusable feature/model functions upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

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
    backtest_forecast,
    quantile_forecast,
)

UPSTREAM_MODEL_NAME = "upstream_lear"
UPSTREAM_MODEL_VERSION = f"da_price_forecasting:{MODEL_VERSION}"


class UpstreamBackendUnavailable(RuntimeError):
    """Raised when the upstream backend cannot be imported or used."""


@dataclass(frozen=True)
class UpstreamModules:
    engineering: object
    lear: object


def load_upstream_modules() -> UpstreamModules:
    try:
        from da_price_forecasting.features import engineering
        from da_price_forecasting.models import lear
    except ImportError as exc:
        raise UpstreamBackendUnavailable(
            "The upstream da_price_forecasting package is not importable. "
            "Install oeds-post-scripts with the price-forecast extra."
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
    end = (daily_index.max() + pd.DateOffset(days=1)).tz_convert("UTC")
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
        residual_offsets = residuals.tail(config.residual_days * 96).quantile(list(config.quantiles))

    return quantile_forecast(point, residual_offsets, config.quantiles)


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm (Meeus/Jones/Butcher).
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def exaa_auction_day(day: date) -> bool:
    """Whether the EXAA holds its day-ahead auction on `day`.

    The EXAA trades on working days except its own holidays. Read from the
    publication times of EXAA prices at ENTSO-E (Oct 2024 - Nov 2026): no auction
    on 1 Jan, Good Friday, Easter Monday, 1 May, Ascension, Whit Monday, 26 Oct
    and 24, 25, 26 and 31 Dec; auctions on 6 Jan, 15 Aug, 1 Nov, 8 Dec and
    Corpus Christi.
    """
    if day.weekday() >= 5:
        return False
    easter = _easter_sunday(day.year)
    holidays = {date(day.year, month, d) for month, d in ((1, 1), (5, 1), (10, 26), (12, 24), (12, 25), (12, 26), (12, 31))}
    holidays |= {easter + timedelta(days=offset) for offset in (-2, 1, 39, 50)}
    return day not in holidays


def exaa_is_stale(target_date: date) -> bool:
    """No EXAA auction on the day before: the target day's EXAA comes from an
    earlier auction, two or more days ahead (Sundays, Mondays, after holidays)."""
    return not exaa_auction_day(target_date - timedelta(days=1))


def stale_exaa_shift(
    price: pd.Series,
    exaa: pd.Series | None,
    target_date: date,
    config: PriceForecastConfig,
) -> float:
    """Level shift for a Sunday or Monday: `stale_spread_weight` times the mean
    SDAC - EXAA of the day before.

    The day before (Saturday, Sunday) got its EXAA from the same Friday auction,
    and its SDAC is known when the forecast is made, so the spread shows how far
    that auction missed. After a holiday the day before is the holiday itself,
    and its spread made the forecast worse (14 cases from May 2025 to Oct 2026),
    so other days get no shift. 0 as well when a quarter-hour of the day before
    is missing.
    """
    if target_date.weekday() not in (6, 0):
        return 0.0
    start = pd.Timestamp(target_date).tz_localize(BERLIN_TZ) - pd.DateOffset(days=1)
    day_before = pd.date_range(start, start + pd.DateOffset(days=1), freq=config.frequency, inclusive="left").tz_convert("UTC")
    spread = _as_utc_series(price, "price").reindex(day_before) - _as_utc_series(exaa, "exaa").reindex(day_before)
    if spread.isna().any():
        return 0.0
    return config.stale_spread_weight * float(spread.mean())


def forecast_day_upstream(
    price: pd.Series,
    exaa: pd.Series | None,
    covariates: pd.DataFrame | None,
    target_date: date,
    config: PriceForecastConfig,
    variant: str = "exaa_only",
) -> ForecastResult:
    modules = load_upstream_modules()
    X, Y, _ = _build_upstream_xy(modules, price, exaa, covariates, target_date, config, variant)
    forecast_day_index = pd.DatetimeIndex([pd.Timestamp(target_date).tz_localize(BERLIN_TZ)])
    # LEAR cannot train on a day without a complete price curve (a gap in the data,
    # or a day before the price history starts); scikit-learn then fails with
    # "Input y contains NaN". Drop such days; the target day itself has no prices yet.
    usable = Y.notna().all(axis=1) | (Y.index == forecast_day_index[0])
    X, Y = X[usable], Y[usable]
    train_rows = X[(X.index >= forecast_day_index[0] - pd.Timedelta(days=config.train_days)) & (X.index < forecast_day_index[0])]
    if len(train_rows) < max(7, config.min_training_rows // 96):
        raise ValueError(
            f"Insufficient upstream LEAR training days: {len(train_rows)} < {max(7, config.min_training_rows // 96)}."
        )

    # Mean of LEAR fits over several training windows (`train_days` and the shorter
    # `short_train_days`), see PriceForecastConfig.
    windows = sorted({days for days in config.short_train_days if days < config.train_days} | {config.train_days})
    forecasts = []
    for days in windows:
        forecast_df, _, _, _, _ = modules.lear.rolling_point_forecast(
            X=X,
            Y=Y,
            forecast_days=forecast_day_index,
            train_days=days,
            lars_start_date=pd.Timestamp("2100-01-01", tz=BERLIN_TZ),
        )
        if forecast_df.empty:
            raise ValueError(f"Upstream LEAR ({days} training days) did not return forecast rows.")
        forecasts.append(forecast_df["y_pred"].to_numpy(dtype=float))

    # LEAR returns 96 values per local wall-clock MTU (4 * hour + minute // 15; the
    # upstream feature pivots average the repeated hour and interpolate the skipped
    # one) but labels them local midnight + 15 min * MTU, which is shifted by one hour
    # after a clock change. Deliver every quarter-hour from local midnight to the next
    # local midnight instead and look up its wall-clock MTU: on the 25-hour day both
    # 02:xx instances get the 02:xx value, on the 23-hour day 02:xx does not exist.
    delivery_local = pd.date_range(
        forecast_day_index[0],
        forecast_day_index[0] + pd.DateOffset(days=1),
        freq=config.frequency,
        inclusive="left",
    )
    mtu = delivery_local.hour * 4 + delivery_local.minute // 15
    y_pred = np.mean(forecasts, axis=0)[mtu]
    y_true = forecast_df["y_true"].to_numpy(dtype=float)[mtu]
    index_utc = delivery_local.tz_convert("UTC")
    # Mean with the EXAA price of the target day; quarter-hours without EXAA keep LEAR.
    exaa_day = _as_utc_series(exaa, "exaa").reindex(index_utc).to_numpy(dtype=float)
    stale = variant in {"exaa", "exaa_only"} and exaa_is_stale(target_date)
    weight = config.stale_exaa_weight if stale else config.exaa_weight
    y_pred = np.where(np.isnan(exaa_day), y_pred, (1 - weight) * y_pred + weight * exaa_day)
    if stale:
        y_pred = y_pred + stale_exaa_shift(price, exaa, target_date, config)
    point = pd.DataFrame(
        {
            "delivery_start_utc": index_utc,
            "delivery_end_utc": list(index_utc[1:]) + [index_utc[-1] + pd.Timedelta(config.frequency)],
            "value_eur_mwh": y_pred,
        }
    )
    actual = pd.Series(y_true, index=index_utc)
    predicted = pd.Series(y_pred, index=index_utc)
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
    variant: str = "exaa_only",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return backtest_forecast(
        price,
        exaa,
        covariates,
        target_dates,
        config,
        forecast_fn=partial(forecast_day_upstream, variant=variant),
    )
