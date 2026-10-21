# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scripts.lib.gapfiller.core import GAPFILL_METHODS, SeriesFillConfig, fill_table

if TYPE_CHECKING:
    from scripts.lib.gapfiller.config import GapfillJobConfig
    from sqlalchemy import Engine


@dataclass(frozen=True)
class SelfTestResult:
    test_name: str
    status: str
    expected_filled: int
    actual_filled: int
    missing_after: int
    message: str
    fault_type: str = ""
    method: str = ""
    description: str = ""


@dataclass(frozen=True)
class SelfTestCase:
    name: str
    description: str
    fault_type: str
    dataframe: pd.DataFrame
    config: SeriesFillConfig
    expected_filled: int

    @property
    def method(self) -> str:
        return self.config.method

    @property
    def source_rows(self) -> int:
        return len(self.dataframe)


@dataclass(frozen=True)
class HoldoutDataset:
    name: str
    label: str
    description: str
    dataframe: pd.DataFrame
    config: SeriesFillConfig
    recommended_gap_start: int
    recommended_gap_length: int

    @property
    def method(self) -> str:
        return self.config.method

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

    @property
    def max_gap_length(self) -> int:
        return max(1, min(self.config.max_gap_periods, self.row_count - 2))


@dataclass(frozen=True)
class HoldoutTestResult:
    dataset_name: str
    dataset_label: str
    status: str
    fault_type: str
    method: str
    gap_start_index: int
    gap_length_periods: int
    gap_start_time: pd.Timestamp
    gap_end_time: pd.Timestamp
    expected_points: int
    compared_points: int
    actual_filled: int
    missing_after: int
    mean_absolute_error: float | None
    root_mean_squared_error: float | None
    max_absolute_error: float | None
    mean_absolute_percentage_error: float | None
    message: str


def list_self_test_cases() -> list[SelfTestCase]:
    return _test_cases()


def list_holdout_datasets() -> list[HoldoutDataset]:
    return _holdout_datasets()


def run_self_tests(test_names: Iterable[str] | None = None) -> tuple[str, list[SelfTestResult], pd.DataFrame]:
    run_id = str(uuid.uuid4())
    checked_at = pd.Timestamp.now(tz="UTC")
    results: list[SelfTestResult] = []
    series_outputs: list[pd.DataFrame] = []

    for test_case in _select_test_cases(test_names):
        fill_result = fill_table(test_case.dataframe, test_case.config, run_id, checked_at)
        actual_filled = sum(metric.filled_values for metric in fill_result.metrics)
        missing_after = sum(metric.missing_after for metric in fill_result.metrics)
        status = "passed" if actual_filled == test_case.expected_filled and missing_after == 0 else "failed"
        message = (
            ""
            if status == "passed"
            else f"expected {test_case.expected_filled} fills, got {actual_filled}, missing_after={missing_after}"
        )
        results.append(
            SelfTestResult(
                test_name=test_case.name,
                status=status,
                expected_filled=test_case.expected_filled,
                actual_filled=actual_filled,
                missing_after=missing_after,
                message=message,
                fault_type=test_case.fault_type,
                method=test_case.method,
                description=test_case.description,
            )
        )
        series_outputs.append(_series_for_dashboard(test_case.name, test_case.dataframe, fill_result.dataframe, checked_at))

    series_df = pd.concat(series_outputs, ignore_index=True) if series_outputs else pd.DataFrame()
    return run_id, results, series_df


def run_holdout_test(
    dataset_name: str,
    gap_length_periods: int,
    *,
    gap_start_index: int | None = None,
    fault_type: str = "value_gap",
    method: str | None = None,
) -> tuple[str, HoldoutTestResult, pd.DataFrame]:
    dataset = _get_holdout_dataset(dataset_name)
    config = _override_config_method(dataset.config, method)
    gap_start_index, gap_length_periods = _validate_holdout_window(dataset, gap_start_index, gap_length_periods)
    if fault_type not in {"value_gap", "timestamp_gap"}:
        raise ValueError("fault_type must be one of: value_gap, timestamp_gap")

    run_id = str(uuid.uuid4())
    checked_at = pd.Timestamp.now(tz="UTC")
    truth = dataset.dataframe.copy()
    truth_window = truth.iloc[gap_start_index : gap_start_index + gap_length_periods].copy()
    faulted = _inject_holdout_fault(truth, gap_start_index, gap_length_periods, fault_type)

    fill_result = fill_table(faulted, config, run_id, checked_at)
    filled = fill_result.dataframe.copy()
    actual_filled = int(
        filled["gapfill_filled_columns"].astype(str).str.contains("Value", regex=False).sum()
        if "gapfill_filled_columns" in filled
        else 0
    )
    missing_after = sum(metric.missing_after for metric in fill_result.metrics)
    metrics = _calculate_holdout_error(truth_window, filled)
    compared_points = int(metrics.pop("compared_points"))
    status = "passed" if compared_points == gap_length_periods and missing_after == 0 else "failed"
    message = (
        ""
        if status == "passed"
        else f"compared {compared_points}/{gap_length_periods} removed points, missing_after={missing_after}"
    )
    result = HoldoutTestResult(
        dataset_name=dataset.name,
        dataset_label=dataset.label,
        status=status,
        fault_type=fault_type,
        method=config.method,
        gap_start_index=gap_start_index,
        gap_length_periods=gap_length_periods,
        gap_start_time=pd.Timestamp(truth_window["DateTime"].iloc[0]),
        gap_end_time=pd.Timestamp(truth_window["DateTime"].iloc[-1]),
        expected_points=gap_length_periods,
        compared_points=compared_points,
        actual_filled=actual_filled,
        missing_after=missing_after,
        mean_absolute_error=metrics["mean_absolute_error"],
        root_mean_squared_error=metrics["root_mean_squared_error"],
        max_absolute_error=metrics["max_absolute_error"],
        mean_absolute_percentage_error=metrics["mean_absolute_percentage_error"],
        message=message,
    )
    series_df = _series_for_holdout_dashboard(
        f"holdout_{dataset.name}",
        truth,
        faulted,
        filled,
        gap_start_index,
        gap_length_periods,
        checked_at,
    )
    return run_id, result, series_df


def write_self_test_results(engine: Engine, job: GapfillJobConfig) -> list[SelfTestResult]:
    from scripts.lib.gapfiller.db import ensure_control_tables, qualified
    from sqlalchemy import text

    ensure_control_tables(engine, job.target_schema)
    run_id, results, series_df = run_self_tests()
    checked_at = pd.Timestamp.now(tz="UTC")

    result_rows = [
        {
            "run_id": run_id,
            "test_name": result.test_name,
            "status": result.status,
            "expected_filled": result.expected_filled,
            "actual_filled": result.actual_filled,
            "missing_after": result.missing_after,
            "message": result.message,
            "checked_at": checked_at.to_pydatetime(),
        }
        for result in results
    ]

    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {qualified(job.target_schema, 'gapfill_test_results')}"))
        conn.execute(text(f"DELETE FROM {qualified(job.target_schema, 'gapfill_test_series')}"))
        pd.DataFrame(result_rows).to_sql(
            "gapfill_test_results",
            con=conn,
            schema=job.target_schema,
            if_exists="append",
            index=False,
        )
        if not series_df.empty:
            series_df["run_id"] = run_id
            series_df["checked_at"] = checked_at.to_pydatetime()
            series_df.to_sql(
                "gapfill_test_series",
                con=conn,
                schema=job.target_schema,
                if_exists="append",
                index=False,
            )

    return results


def _get_holdout_dataset(dataset_name: str) -> HoldoutDataset:
    datasets = {dataset.name: dataset for dataset in _holdout_datasets()}
    try:
        return datasets[dataset_name]
    except KeyError as exc:
        raise ValueError(f"Unknown holdout dataset '{dataset_name}'. Known datasets: {', '.join(sorted(datasets))}") from exc


def _validate_holdout_window(
    dataset: HoldoutDataset,
    gap_start_index: int | None,
    gap_length_periods: int,
) -> tuple[int, int]:
    try:
        gap_length = int(gap_length_periods)
    except (TypeError, ValueError) as exc:
        raise ValueError("gap_length_periods must be an integer.") from exc

    if gap_length < 1:
        raise ValueError("gap_length_periods must be at least 1.")
    if gap_length > dataset.max_gap_length:
        raise ValueError(f"gap_length_periods must be at most {dataset.max_gap_length} for {dataset.name}.")

    if gap_start_index is None:
        start_index = dataset.recommended_gap_start
    else:
        try:
            start_index = int(gap_start_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("gap_start_index must be an integer.") from exc

    if start_index < 1:
        raise ValueError("gap_start_index must be at least 1 so the gap has left context.")
    if start_index + gap_length >= dataset.row_count:
        raise ValueError(
            f"gap_start_index + gap_length_periods must be smaller than {dataset.row_count} "
            "so the gap has right context."
        )

    return start_index, gap_length


def _override_config_method(config: SeriesFillConfig, method: str | None) -> SeriesFillConfig:
    if method is None or not str(method).strip():
        return config

    method_value = str(method).strip()
    if method_value not in GAPFILL_METHODS:
        raise ValueError(f"method must be one of: {', '.join(GAPFILL_METHODS)}")

    return replace(config, method=method_value)


def _inject_holdout_fault(
    truth: pd.DataFrame,
    gap_start_index: int,
    gap_length_periods: int,
    fault_type: str,
) -> pd.DataFrame:
    faulted = truth.copy()
    window_index = faulted.index[gap_start_index : gap_start_index + gap_length_periods]
    if fault_type == "timestamp_gap":
        return faulted.drop(index=window_index).reset_index(drop=True)

    faulted.loc[window_index, "Value"] = np.nan
    return faulted


def _calculate_holdout_error(truth_window: pd.DataFrame, filled: pd.DataFrame) -> dict[str, float | int | None]:
    joined = truth_window[["DateTime", "Value"]].rename(columns={"Value": "expected"}).merge(
        filled[["DateTime", "Value"]].rename(columns={"Value": "actual"}),
        on="DateTime",
        how="left",
    )
    comparable = joined.dropna(subset=["expected", "actual"]).copy()
    if comparable.empty:
        return {
            "compared_points": 0,
            "mean_absolute_error": None,
            "root_mean_squared_error": None,
            "max_absolute_error": None,
            "mean_absolute_percentage_error": None,
        }

    errors = comparable["actual"].astype(float) - comparable["expected"].astype(float)
    absolute_errors = errors.abs()
    non_zero_expected = comparable["expected"].astype(float).abs() > 1e-12
    if non_zero_expected.any():
        mape = float((absolute_errors[non_zero_expected] / comparable.loc[non_zero_expected, "expected"].abs()).mean() * 100.0)
    else:
        mape = None

    return {
        "compared_points": int(len(comparable)),
        "mean_absolute_error": float(absolute_errors.mean()),
        "root_mean_squared_error": float(np.sqrt(np.square(errors).mean())),
        "max_absolute_error": float(absolute_errors.max()),
        "mean_absolute_percentage_error": mape,
    }


def _select_test_cases(test_names: Iterable[str] | None) -> list[SelfTestCase]:
    cases_by_name = {test_case.name: test_case for test_case in _test_cases()}
    if test_names is None:
        return list(cases_by_name.values())

    selected_names = []
    seen = set()
    for raw_name in test_names:
        name = str(raw_name).strip()
        if name and name not in seen:
            selected_names.append(name)
            seen.add(name)

    if not selected_names:
        return list(cases_by_name.values())

    unknown_names = sorted(set(selected_names) - set(cases_by_name))
    if unknown_names:
        raise ValueError(f"Unknown gapfill self-test(s): {', '.join(unknown_names)}")

    return [cases_by_name[name] for name in selected_names]


def _holdout_datasets() -> list[HoldoutDataset]:
    return [
        _holdout_linear_hourly(),
        _holdout_daily_seasonal(),
        _holdout_weekly_pattern(),
    ]


def _test_cases() -> list[SelfTestCase]:
    return [
        _linear_value_gap_case(),
        _missing_timestamp_case(),
        _seasonal_case(),
    ]


def _holdout_linear_hourly() -> HoldoutDataset:
    index = pd.date_range("2026-01-01", periods=72, freq="h", tz="UTC")
    dataframe = pd.DataFrame({
        "DateTime": index,
        "Value": np.arange(72, dtype=float),
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="HoldoutLinearHourly",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="linear",
        max_gap_periods=24,
    )
    return HoldoutDataset(
        name="linear_hourly",
        label="Linear hourly ramp",
        description="Hourly linearly increasing values; linear interpolation should reconstruct removed segments exactly.",
        dataframe=dataframe,
        config=config,
        recommended_gap_start=24,
        recommended_gap_length=6,
    )


def _holdout_daily_seasonal() -> HoldoutDataset:
    index = pd.date_range("2026-01-01", periods=24 * 14, freq="h", tz="UTC")
    hours = np.arange(len(index), dtype=float)
    values = 100.0 + 14.0 * np.sin(hours * 2 * np.pi / 24) + 0.05 * hours
    dataframe = pd.DataFrame({
        "DateTime": index,
        "Value": values,
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="HoldoutDailySeasonal",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="donor_refined",
        period=pd.Timedelta(hours=24),
        candidate_periods=(pd.Timedelta(hours=24), pd.Timedelta(days=7)),
        donor_context_periods=6,
        donor_search_radius=pd.Timedelta(days=10),
        refinement_periods=3,
        max_gap_periods=24,
    )
    return HoldoutDataset(
        name="daily_seasonal",
        label="Daily seasonal load shape",
        description="Two weeks of hourly daily seasonality with a small trend; useful for donor matching error checks.",
        dataframe=dataframe,
        config=config,
        recommended_gap_start=24 * 8 + 6,
        recommended_gap_length=8,
    )


def _holdout_weekly_pattern() -> HoldoutDataset:
    index = pd.date_range("2026-01-01", periods=24 * 28, freq="h", tz="UTC")
    hours = np.arange(len(index), dtype=float)
    daily = 12.0 * np.sin(hours * 2 * np.pi / 24)
    weekday_boost = np.where(pd.Series(index).dt.dayofweek.to_numpy() < 5, 8.0, -5.0)
    values = 180.0 + daily + weekday_boost + 0.03 * hours
    dataframe = pd.DataFrame({
        "DateTime": index,
        "Value": values,
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="HoldoutWeeklyPattern",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="donor_refined",
        period=pd.Timedelta(days=7),
        candidate_periods=(pd.Timedelta(hours=24), pd.Timedelta(days=7)),
        donor_context_periods=8,
        donor_search_radius=pd.Timedelta(days=21),
        refinement_periods=4,
        max_gap_periods=24,
    )
    return HoldoutDataset(
        name="weekly_pattern",
        label="Weekly plus daily pattern",
        description="Four weeks with weekday/weekend structure and daily shape; useful for daily versus weekly donor matching.",
        dataframe=dataframe,
        config=config,
        recommended_gap_start=24 * 18 + 8,
        recommended_gap_length=10,
    )


def _linear_value_gap_case() -> SelfTestCase:
    index = pd.date_range("2026-01-01", periods=12, freq="h", tz="UTC")
    values = np.arange(12, dtype=float)
    values[4:7] = np.nan
    dataframe = pd.DataFrame({
        "DateTime": index,
        "Value": values,
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="SelfTestLinear",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="linear",
        max_gap_periods=6,
    )
    return SelfTestCase(
        name="linear_value_gap",
        description="Injects NaN values into an otherwise complete hourly series.",
        fault_type="value_gap",
        dataframe=dataframe,
        config=config,
        expected_filled=3,
    )


def _missing_timestamp_case() -> SelfTestCase:
    index = pd.date_range("2026-01-02", periods=12, freq="h", tz="UTC")
    dataframe = pd.DataFrame({
        "DateTime": index.delete([5, 6]),
        "Value": np.delete(np.arange(12, dtype=float), [5, 6]),
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="SelfTestMissingTimestamp",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="linear",
        max_gap_periods=6,
    )
    return SelfTestCase(
        name="missing_timestamp_gap",
        description="Removes timestamps so the gapfiller must recreate rows before imputing values.",
        fault_type="timestamp_gap",
        dataframe=dataframe,
        config=config,
        expected_filled=2,
    )


def _seasonal_case() -> SelfTestCase:
    index = pd.date_range("2026-01-01", periods=72, freq="h", tz="UTC")
    values = 100 + 10 * np.sin(np.arange(72) * 2 * np.pi / 24)
    values[48:51] = np.nan
    dataframe = pd.DataFrame({
        "DateTime": index,
        "Value": values,
        "Area": "DE",
    })
    config = SeriesFillConfig(
        table_name="SelfTestSeasonal",
        time_column="DateTime",
        value_columns=("Value",),
        groupby_columns=("Area",),
        method="donor_refined",
        period=pd.Timedelta(hours=24),
        candidate_periods=(pd.Timedelta(hours=24), pd.Timedelta(days=7)),
        donor_context_periods=4,
        max_gap_periods=6,
    )
    return SelfTestCase(
        name="donor_refined_seasonal_gap",
        description="Injects a short daily seasonal gap and fills it with donor matching plus edge refinement.",
        fault_type="seasonal_value_gap",
        dataframe=dataframe,
        config=config,
        expected_filled=3,
    )


def _series_for_dashboard(
    test_name: str,
    original: pd.DataFrame,
    filled: pd.DataFrame,
    checked_at: pd.Timestamp,
) -> pd.DataFrame:
    original_series = original[["DateTime", "Value"]].copy()
    original_series["series_name"] = "source"
    original_series["is_original"] = True
    original_series["was_filled"] = False

    filled_series = filled[["DateTime", "Value", "gapfill_filled_columns"]].copy()
    filled_series["series_name"] = "gapfilled"
    filled_series["is_original"] = False
    filled_series["was_filled"] = filled_series["gapfill_filled_columns"].astype(str).str.contains("Value", regex=False)
    filled_series = filled_series.drop(columns=["gapfill_filled_columns"])

    output = pd.concat([original_series, filled_series], ignore_index=True)
    output = output.rename(columns={"DateTime": "time", "Value": "value"})
    output["test_name"] = test_name
    output["checked_at"] = checked_at.to_pydatetime()
    return output[["test_name", "time", "series_name", "value", "is_original", "was_filled", "checked_at"]]


def _series_for_holdout_dashboard(
    test_name: str,
    truth: pd.DataFrame,
    faulted: pd.DataFrame,
    filled: pd.DataFrame,
    gap_start_index: int,
    gap_length_periods: int,
    checked_at: pd.Timestamp,
) -> pd.DataFrame:
    truth_series = truth[["DateTime", "Value"]].copy()
    truth_series["series_name"] = "truth"
    truth_series["is_original"] = True
    truth_series["was_filled"] = False

    source_display = truth[["DateTime", "Value"]].copy()
    source_window = source_display.index[gap_start_index : gap_start_index + gap_length_periods]
    source_display.loc[source_window, "Value"] = np.nan
    source_display["series_name"] = "source"
    source_display["is_original"] = False
    source_display["was_filled"] = False

    if not faulted["DateTime"].equals(source_display["DateTime"]):
        faulted_lookup = faulted.set_index("DateTime")["Value"]
        source_display["Value"] = source_display["DateTime"].map(faulted_lookup)

    filled_series = filled[["DateTime", "Value", "gapfill_filled_columns"]].copy()
    filled_series["series_name"] = "gapfilled"
    filled_series["is_original"] = False
    filled_series["was_filled"] = filled_series["gapfill_filled_columns"].astype(str).str.contains("Value", regex=False)
    filled_series = filled_series.drop(columns=["gapfill_filled_columns"])

    output = pd.concat([truth_series, source_display, filled_series], ignore_index=True)
    output = output.rename(columns={"DateTime": "time", "Value": "value"})
    output["test_name"] = test_name
    output["checked_at"] = checked_at.to_pydatetime()
    return output[["test_name", "time", "series_name", "value", "is_original", "was_filled", "checked_at"]]
