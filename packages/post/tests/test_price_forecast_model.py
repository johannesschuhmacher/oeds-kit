# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest

import pandas as pd
from oeds_price_forecast.model import (
    PriceForecastConfig,
    backtest_forecast,
    delivery_index_for_local_date,
    forecast_day,
    generate_self_test_series,
)
from scripts.run_price_forecast import (
    _combine_covariates,
    _combine_training_fallback_series,
)


class PriceForecastModelTest(unittest.TestCase):
    def test_delivery_index_uses_local_market_day(self) -> None:
        index = delivery_index_for_local_date(pd.Timestamp("2026-05-18").date())

        self.assertEqual(len(index), 96)
        self.assertEqual(str(index[0]), "2026-05-17 22:00:00+00:00")
        self.assertEqual(str(index[-1]), "2026-05-18 21:45:00+00:00")

    def test_forecast_day_returns_point_and_quantile_rows(self) -> None:
        target_date = pd.Timestamp("2026-05-18").date()
        price, exaa, covariates = generate_self_test_series(days=100, end_date=target_date)
        config = PriceForecastConfig(train_days=56)

        result = forecast_day(price, exaa, covariates, target_date, config)

        self.assertEqual(len(result.point_forecast), 96)
        self.assertEqual(len(result.quantile_forecast), 96 * len(config.quantiles))
        self.assertIn("mae_eur_mwh", set(result.metrics["metric"]))
        self.assertIn("exaa_price_eur_mwh", result.feature_columns)
        self.assertIn("cov_load_mw", result.feature_columns)

    def test_backtest_returns_aggregate_metrics(self) -> None:
        target_date = pd.Timestamp("2026-05-18").date()
        price, exaa, covariates = generate_self_test_series(days=100, end_date=target_date)
        config = PriceForecastConfig(train_days=56)
        dates = [
            pd.Timestamp("2026-05-15").date(),
            pd.Timestamp("2026-05-16").date(),
        ]

        forecasts, metrics = backtest_forecast(price, exaa, covariates, dates, config)

        self.assertEqual(len(forecasts), 192)
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


if __name__ == "__main__":
    unittest.main()
