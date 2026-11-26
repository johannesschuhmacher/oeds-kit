# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from oeds_price_forecast.model import PriceForecastConfig, generate_self_test_series
from oeds_price_forecast.upstream import (
    backtest_forecast_upstream,
    exaa_auction_day,
    exaa_is_stale,
    forecast_day_upstream,
    stale_exaa_shift,
)
from scripts.run_price_forecast import (
    _combine_covariates,
    _combine_training_fallback_series,
    _has_full_day,
)


# The upstream LEAR fit takes several seconds per forecast day, so the tests use
# short training windows and few target days.
class PriceForecastModelTest(unittest.TestCase):
    def test_forecast_day_returns_point_and_quantile_rows(self) -> None:
        target_date = pd.Timestamp("2026-05-18").date()
        price, exaa, covariates = generate_self_test_series(days=35, end_date=target_date)
        config = PriceForecastConfig(train_days=14)

        result = forecast_day_upstream(price, exaa, covariates, target_date, config)

        self.assertEqual(len(result.point_forecast), 96)
        self.assertEqual(str(result.point_forecast["delivery_start_utc"].iloc[0]), "2026-05-17 22:00:00+00:00")
        self.assertEqual(len(result.quantile_forecast), 96 * len(config.quantiles))
        self.assertIn("mae_eur_mwh", set(result.metrics["metric"]))
        self.assertIn("exaa_d0_mtu_00", result.feature_columns)
        self.assertIn("load_d0_mtu_00", result.feature_columns)

    def test_point_forecast_is_mean_of_lear_and_exaa(self) -> None:
        # Tuesday: exaa_weight. Monday (EXAA from Friday): stale_exaa_weight plus the shift.
        for day, weight in (("2026-05-19", 0.5), ("2026-05-18", 0.2)):
            with self.subTest(day=day):
                target_date = pd.Timestamp(day).date()
                price, exaa, covariates = generate_self_test_series(days=35, end_date=target_date)
                config = PriceForecastConfig(train_days=14)
                lear_only = PriceForecastConfig(train_days=14, exaa_weight=0.0, stale_exaa_weight=0.0, stale_spread_weight=0.0)

                lear = forecast_day_upstream(price, exaa, covariates, target_date, lear_only).point_forecast
                mixed = forecast_day_upstream(price, exaa, covariates, target_date, config).point_forecast

                exaa_day = exaa.reindex(pd.DatetimeIndex(mixed["delivery_start_utc"])).to_numpy()
                shift = stale_exaa_shift(price, exaa, target_date, config)
                np.testing.assert_allclose(
                    mixed["value_eur_mwh"], (1 - weight) * lear["value_eur_mwh"] + weight * exaa_day + shift
                )

    def test_lear_is_mean_over_training_windows(self) -> None:
        target_date = pd.Timestamp("2026-05-19").date()
        price, exaa, covariates = generate_self_test_series(days=42, end_date=target_date)
        lear = dict(exaa_weight=0.0, stale_exaa_weight=0.0, stale_spread_weight=0.0)

        def point(**kwargs):
            config = PriceForecastConfig(**lear, **kwargs)
            return forecast_day_upstream(price, exaa, covariates, target_date, config).point_forecast["value_eur_mwh"]

        np.testing.assert_allclose(
            point(train_days=21, short_train_days=(14,)),
            (point(train_days=21, short_train_days=()) + point(train_days=14, short_train_days=())) / 2,
        )

    def test_forecast_day_covers_local_day_on_clock_changes(self) -> None:
        # LEAR alone: the EXAA mean would give the two 02:xx hours their own values
        # (both days are Sundays, hence also stale_exaa_weight).
        config = PriceForecastConfig(train_days=14, exaa_weight=0.0, stale_exaa_weight=0.0)
        # 25 Oct 2026: 25 hours, 02:00-03:00 twice; 29 Mar 2026: 23 hours, no 02:00.
        for day, rows, first, last in [
            ("2026-10-25", 100, "2026-10-24 22:00:00+00:00", "2026-10-25 22:45:00+00:00"),
            ("2026-03-29", 92, "2026-03-28 23:00:00+00:00", "2026-03-29 21:45:00+00:00"),
        ]:
            with self.subTest(day=day):
                target_date = pd.Timestamp(day).date()
                price, exaa, covariates = generate_self_test_series(
                    days=35, end_date=target_date + pd.Timedelta(days=1)
                )

                point = forecast_day_upstream(price, exaa, covariates, target_date, config).point_forecast

                self.assertEqual(len(point), rows)
                self.assertEqual(str(point["delivery_start_utc"].iloc[0]), first)
                self.assertEqual(str(point["delivery_start_utc"].iloc[-1]), last)
                local_hour = pd.DatetimeIndex(point["delivery_start_utc"]).tz_convert("Europe/Berlin").hour
                if rows == 100:
                    repeated = point.loc[local_hour == 2, "value_eur_mwh"].to_numpy()
                    self.assertEqual(len(repeated), 8)
                    self.assertEqual(list(repeated[:4]), list(repeated[4:]))
                else:
                    self.assertNotIn(2, set(local_hour))

    def test_backtest_returns_aggregate_metrics(self) -> None:
        target_date = pd.Timestamp("2026-05-18").date()
        price, exaa, covariates = generate_self_test_series(days=35, end_date=target_date)
        config = PriceForecastConfig(train_days=14)
        dates = [pd.Timestamp("2026-05-16").date()]

        forecasts, metrics = backtest_forecast_upstream(price, exaa, covariates, dates, config)

        self.assertEqual(len(forecasts), 96)
        self.assertIn("actual_eur_mwh", forecasts.columns)
        self.assertTrue(metrics["target_date"].isna().any())

    def test_training_fallback_uses_fms_history_and_api_fresh_values(self) -> None:
        index = pd.date_range("2026-05-01", periods=6, freq="h", tz="UTC")
        training_end = pd.Timestamp("2026-05-01 03:00", tz="UTC")
        fms = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0], index=index)
        api = pd.Series([20.0, 21.0, 22.0, 23.0, 24.0, 25.0], index=index)

        combined = _combine_training_fallback_series(
            "price_eur_mwh",
            fms,
            api,
            training_end,
            api_training_ready=False,
        )

        self.assertEqual(combined.loc[index[1]], 11.0)
        self.assertEqual(combined.loc[index[4]], 24.0)

    def test_covariates_prefer_later_sources_for_overlapping_values(self) -> None:
        index = pd.date_range("2026-05-01", periods=2, freq="h", tz="UTC")
        fms = pd.DataFrame({"load_mw": [1.0, 2.0]}, index=index)
        api = pd.DataFrame({"load_mw": [10.0, None]}, index=index)

        combined = _combine_covariates(fms, api)

        self.assertEqual(combined.loc[index[0], "load_mw"], 10.0)
        self.assertEqual(combined.loc[index[1], "load_mw"], 2.0)


def test_stale_exaa_shift_is_weighted_mean_spread_of_the_day_before():
    config = PriceForecastConfig(stale_spread_weight=0.5)
    sunday = pd.date_range("2026-11-14 23:00", periods=96, freq="15min", tz="UTC")
    price = pd.Series(110.0, index=sunday)
    exaa = pd.Series(100.0, index=sunday)

    assert stale_exaa_shift(price, exaa, pd.Timestamp("2026-11-16").date(), config) == 5.0
    assert stale_exaa_shift(price, exaa, pd.Timestamp("2026-11-17").date(), config) == 0.0
    assert stale_exaa_shift(price.iloc[1:], exaa, pd.Timestamp("2026-11-16").date(), config) == 0.0


def test_exaa_calendar_matches_observed_auction_days():
    day = lambda text: pd.Timestamp(text).date()
    # No auction on weekends, Good Friday, Whit Monday, 26 Oct, Christmas; auctions on 8 Dec.
    for text in ("2026-11-28", "2026-04-03", "2026-05-25", "2026-10-26", "2026-12-24", "2026-12-31"):
        assert not exaa_auction_day(day(text)), text
    for text in ("2026-11-27", "2026-12-08", "2026-01-06"):
        assert exaa_auction_day(day(text)), text
    # Stale: Sunday, Monday, Tuesday after Whit Monday; fresh: Saturday, Thursday.
    assert [exaa_is_stale(day(t)) for t in ("2026-11-29", "2026-11-30", "2026-05-26", "2026-11-28", "2026-11-26")] == [
        True, True, True, False, False
    ]
    # The spread shift is for Sundays and Mondays only.
    tuesday = pd.date_range("2026-05-24 22:00", periods=96, freq="15min", tz="UTC")
    assert stale_exaa_shift(pd.Series(110.0, index=tuesday), pd.Series(100.0, index=tuesday), day("2026-05-26"), PriceForecastConfig()) == 0.0


def test_has_full_day_needs_every_quarter_hour_of_the_local_day():
    # 29 Mar 2026: 23-hour day, 92 quarter-hours from 23:00 UTC the day before.
    day = pd.date_range("2026-03-28 23:00", periods=92, freq="15min", tz="UTC")
    exaa = pd.Series(100.0, index=day)
    assert _has_full_day(exaa, pd.Timestamp("2026-03-29").date())
    assert not _has_full_day(exaa.iloc[:-1], pd.Timestamp("2026-03-29").date())
    assert not _has_full_day(exaa, pd.Timestamp("2026-03-30").date())


if __name__ == "__main__":
    unittest.main()

