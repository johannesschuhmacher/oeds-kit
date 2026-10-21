# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from oeds_gapfill.core import SeriesFillConfig, fill_table, infer_frequency
from oeds_gapfill.selftest import (
    list_holdout_datasets,
    list_self_test_cases,
    run_holdout_test,
    run_self_tests,
)


class GapfillerCoreTest(unittest.TestCase):
    def test_infer_frequency_uses_median_delta(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                "2026-01-01T02:00:00Z",
                "2026-01-01T05:00:00Z",
            ]
        )

        self.assertEqual(infer_frequency(index), pd.Timedelta(hours=1))

    def test_linear_gap_fill_fills_short_internal_nan_gap(self) -> None:
        dataframe = pd.DataFrame(
            {
                "DateTime": pd.date_range("2026-01-01", periods=8, freq="h", tz="UTC"),
                "Value": [0.0, 1.0, np.nan, np.nan, 4.0, 5.0, 6.0, 7.0],
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            method="linear",
            max_gap_periods=4,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-02T00:00:00Z")
        )

        self.assertEqual(result.metrics[0].filled_values, 2)
        self.assertEqual(result.metrics[0].missing_after, 0)
        filled = result.dataframe.set_index("DateTime")
        self.assertEqual(filled.loc[pd.Timestamp("2026-01-01T02:00:00Z"), "Value"], 2.0)
        self.assertEqual(filled.loc[pd.Timestamp("2026-01-01T03:00:00Z"), "Value"], 3.0)

    def test_missing_timestamps_are_created_and_filled(self) -> None:
        full_index = pd.date_range("2026-01-01", periods=8, freq="h", tz="UTC")
        dataframe = pd.DataFrame(
            {
                "DateTime": full_index.delete([3, 4]),
                "Value": np.delete(np.arange(8, dtype=float), [3, 4]),
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            method="linear",
            max_gap_periods=4,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-02T00:00:00Z")
        )

        self.assertEqual(len(result.dataframe), 8)
        self.assertEqual(result.metrics[0].created_gap_rows, 2)
        self.assertEqual(result.metrics[0].filled_values, 2)
        self.assertEqual(int(result.dataframe["gapfill_created_row"].sum()), 2)

    def test_large_gap_above_limit_is_left_unfilled(self) -> None:
        dataframe = pd.DataFrame(
            {
                "DateTime": pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC"),
                "Value": [0.0, 1.0, np.nan, np.nan, np.nan, np.nan, 6.0, 7.0, 8.0, 9.0],
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            method="linear",
            max_gap_periods=3,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-02T00:00:00Z")
        )

        self.assertEqual(result.metrics[0].filled_values, 0)
        self.assertEqual(result.metrics[0].missing_after, 4)

    def test_multi_value_table_is_filled_in_one_output(self) -> None:
        dataframe = pd.DataFrame(
            {
                "DateTime": pd.date_range("2026-01-01", periods=8, freq="h", tz="UTC"),
                "Generation": [0.0, 1.0, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0],
                "Consumption": [10.0, 11.0, 12.0, 13.0, np.nan, np.nan, 16.0, 17.0],
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Generation", "Consumption"),
            groupby_columns=("Area",),
            method="linear",
            max_gap_periods=4,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-02T00:00:00Z")
        )

        metrics = {metric.value_column: metric for metric in result.metrics}
        self.assertEqual(metrics["Generation"].filled_values, 1)
        self.assertEqual(metrics["Consumption"].filled_values, 2)
        self.assertIn("Generation", result.dataframe.columns)
        self.assertIn("Consumption", result.dataframe.columns)

    def test_previous_period_method_uses_donor_from_prior_day(self) -> None:
        index = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
        values = np.arange(48, dtype=float)
        values[30] = np.nan
        dataframe = pd.DataFrame(
            {
                "DateTime": index,
                "Value": values,
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            method="previous_period",
            period=pd.Timedelta(hours=24),
            max_gap_periods=2,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-03T00:00:00Z")
        )
        filled = result.dataframe.set_index("DateTime")

        self.assertEqual(filled.loc[index[30], "Value"], 6.0)

    def test_donor_match_uses_best_context_instead_of_fixed_prior_day(self) -> None:
        index = pd.date_range("2026-01-01", periods=96, freq="h", tz="UTC")
        base = 100.0 + 20.0 * np.sin(np.arange(96) * 2 * np.pi / 24)
        values = base.copy()
        values[30:33] = [500.0, 500.0, 500.0]
        expected = values[6:9].copy()
        values[54:57] = np.nan
        dataframe = pd.DataFrame(
            {
                "DateTime": index,
                "Value": values,
                "Area": "DE",
            }
        )
        config = SeriesFillConfig(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            method="donor_match",
            period=pd.Timedelta(hours=24),
            candidate_periods=(pd.Timedelta(hours=24),),
            donor_context_periods=3,
            max_gap_periods=6,
        )

        result = fill_table(
            dataframe, config, "run-1", pd.Timestamp("2026-01-05T00:00:00Z")
        )
        filled = result.dataframe.set_index("DateTime")
        actual = filled.loc[index[54:57], "Value"].to_numpy(dtype="float64")

        np.testing.assert_allclose(actual, expected)
        self.assertFalse(np.allclose(actual, [500.0, 500.0, 500.0]))

    def test_donor_refined_reduces_edge_jumps(self) -> None:
        index = pd.date_range("2026-01-01", periods=72, freq="h", tz="UTC")
        values = np.full(72, np.nan)
        values[23:26] = [8.0, 9.0, 10.0]
        values[26:30] = [100.0, 110.0, 120.0, 130.0]
        values[30:33] = [13.0, 14.0, 15.0]
        values[47:50] = [8.0, 9.0, 10.0]
        values[54:57] = [13.0, 14.0, 15.0]
        dataframe = pd.DataFrame(
            {
                "DateTime": index,
                "Value": values,
                "Area": "DE",
            }
        )
        base_config = dict(
            table_name="Example",
            time_column="DateTime",
            value_columns=("Value",),
            groupby_columns=("Area",),
            period=pd.Timedelta(hours=24),
            candidate_periods=(pd.Timedelta(hours=24),),
            donor_context_periods=3,
            max_gap_periods=4,
        )
        raw = fill_table(
            dataframe,
            SeriesFillConfig(**base_config, method="donor_match"),
            "run-1",
            pd.Timestamp("2026-01-04T00:00:00Z"),
        ).dataframe.set_index("DateTime")
        refined = fill_table(
            dataframe,
            SeriesFillConfig(**base_config, method="donor_refined"),
            "run-2",
            pd.Timestamp("2026-01-04T00:00:00Z"),
        ).dataframe.set_index("DateTime")

        raw_values = raw.loc[index[50:54], "Value"].to_numpy(dtype="float64")
        refined_values = refined.loc[index[50:54], "Value"].to_numpy(dtype="float64")

        self.assertEqual(int(np.isfinite(refined_values).sum()), 4)
        self.assertLess(abs(refined_values[0] - 10.0), abs(raw_values[0] - 10.0))
        self.assertLess(abs(refined_values[-1] - 13.0), abs(raw_values[-1] - 13.0))

    def test_builtin_self_tests_pass(self) -> None:
        _, results, series = run_self_tests()

        self.assertTrue(results)
        self.assertTrue(all(result.status == "passed" for result in results))
        self.assertFalse(series.empty)

    def test_self_test_catalog_describes_fault_injection_cases(self) -> None:
        cases = {test_case.name: test_case for test_case in list_self_test_cases()}

        self.assertIn("linear_value_gap", cases)
        self.assertIn("missing_timestamp_gap", cases)
        self.assertIn("donor_refined_seasonal_gap", cases)
        self.assertEqual(cases["linear_value_gap"].fault_type, "value_gap")
        self.assertEqual(cases["missing_timestamp_gap"].fault_type, "timestamp_gap")
        self.assertEqual(cases["donor_refined_seasonal_gap"].method, "donor_refined")
        self.assertGreater(cases["donor_refined_seasonal_gap"].source_rows, 0)

    def test_self_tests_can_run_selected_fault_injection_case(self) -> None:
        _, results, series = run_self_tests(["missing_timestamp_gap"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].test_name, "missing_timestamp_gap")
        self.assertEqual(results[0].status, "passed")
        self.assertEqual(results[0].actual_filled, 2)
        self.assertTrue((series["test_name"] == "missing_timestamp_gap").all())
        self.assertEqual(int(series["was_filled"].sum()), 2)

    def test_self_tests_reject_unknown_selected_case(self) -> None:
        with self.assertRaises(ValueError):
            run_self_tests(["does_not_exist"])

    def test_holdout_catalog_exposes_selectable_datasets(self) -> None:
        datasets = {dataset.name: dataset for dataset in list_holdout_datasets()}

        self.assertIn("linear_hourly", datasets)
        self.assertIn("daily_seasonal", datasets)
        self.assertGreaterEqual(
            datasets["linear_hourly"].max_gap_length,
            datasets["linear_hourly"].recommended_gap_length,
        )
        self.assertEqual(datasets["daily_seasonal"].method, "donor_refined")

    def test_holdout_test_removes_selected_length_and_calculates_error(self) -> None:
        _, result, series = run_holdout_test(
            "linear_hourly",
            6,
            gap_start_index=24,
            fault_type="value_gap",
            method="linear",
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.gap_length_periods, 6)
        self.assertEqual(result.compared_points, 6)
        self.assertEqual(result.actual_filled, 6)
        self.assertEqual(result.mean_absolute_error, 0.0)
        self.assertEqual(result.root_mean_squared_error, 0.0)
        self.assertEqual(result.max_absolute_error, 0.0)
        self.assertIn("truth", set(series["series_name"]))
        self.assertEqual(int(series["was_filled"].sum()), 6)

    def test_holdout_timestamp_removal_recreates_rows_for_error_check(self) -> None:
        _, result, series = run_holdout_test(
            "linear_hourly",
            4,
            gap_start_index=18,
            fault_type="timestamp_gap",
            method="linear",
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.compared_points, 4)
        self.assertEqual(result.actual_filled, 4)
        self.assertEqual(result.mean_absolute_error, 0.0)
        self.assertEqual(int(series["was_filled"].sum()), 4)

    def test_holdout_rejects_gap_length_without_context(self) -> None:
        with self.assertRaises(ValueError):
            run_holdout_test("linear_hourly", 200, gap_start_index=1)


if __name__ == "__main__":
    unittest.main()
