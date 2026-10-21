# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from scripts.lib.gapfiller.config import GapfillJobConfig, TimeSeriesTableConfig
from scripts.lib.gapfiller.core import (
    GAPFILL_METHODS,
    fill_table,
    group_key_from_values,
)
from scripts.lib.gapfiller.db import (
    ensure_control_tables,
    qualified,
    quote_identifier,
    table_exists,
)
from sqlalchemy import Engine, text


@dataclass(frozen=True)
class DatabaseHoldoutResult:
    run_id: str
    job_name: str
    source_schema: str
    target_schema: str
    table_name: str
    value_column: str
    group_key: str
    method: str
    fault_type: str
    gap_start_time: pd.Timestamp
    gap_end_time: pd.Timestamp
    gap_length_periods: int
    expected_points: int
    compared_points: int
    actual_filled: int
    missing_after: int
    mean_absolute_error: float | None
    root_mean_squared_error: float | None
    max_absolute_error: float | None
    mean_absolute_percentage_error: float | None
    status: str
    message: str
    checked_at: pd.Timestamp


def run_database_holdout_test(
    engine: Engine,
    job: GapfillJobConfig,
    *,
    table_name: str,
    value_column: str | None,
    gap_start_time: pd.Timestamp,
    gap_length_periods: int,
    group_key: str | None = None,
    fault_type: str = "value_gap",
    method: str | None = None,
    context: pd.Timedelta = pd.Timedelta(days=28),
    persist: bool = True,
) -> tuple[DatabaseHoldoutResult, pd.DataFrame]:
    ensure_control_tables(engine, job.target_schema)
    table_config = _select_table_config(job, table_name)
    selected_value_column = value_column or table_config.value_columns[0]
    if selected_value_column not in table_config.value_columns:
        raise ValueError(
            f"value_column must be one of {table_config.value_columns} for table {table_config.table_name}."
        )
    if fault_type not in {"value_gap", "timestamp_gap"}:
        raise ValueError("fault_type must be one of: value_gap, timestamp_gap")

    gap_length = _validate_gap_length(gap_length_periods, table_config)
    holdout_start = _timestamp(gap_start_time)
    read_start = holdout_start - context
    read_end = holdout_start + context
    checked_at = pd.Timestamp.now(tz="UTC")
    run_id = str(uuid.uuid4())

    source = _read_holdout_source(
        engine,
        job,
        table_config,
        selected_value_column,
        read_start,
        read_end,
        group_key,
    )
    selected_source, selected_group_key, start_position = _select_holdout_group(
        source,
        table_config,
        selected_value_column,
        holdout_start,
        gap_length,
        group_key,
    )

    effective_config = replace(
        table_config,
        value_columns=(selected_value_column,),
        method=_override_method(table_config, method),
    )
    truth = selected_source.copy().reset_index(drop=True)
    truth_window = truth.iloc[start_position : start_position + gap_length].copy()
    faulted = _inject_fault(truth, start_position, gap_length, selected_value_column, fault_type)
    fill_result = fill_table(faulted, effective_config.to_series_config(), run_id, checked_at)
    filled = fill_result.dataframe.copy()

    actual_filled = int(
        filled["gapfill_filled_columns"].astype(str).str.contains(selected_value_column, regex=False).sum()
        if "gapfill_filled_columns" in filled
        else 0
    )
    missing_after = sum(metric.missing_after for metric in fill_result.metrics)
    error_metrics = _calculate_error(truth_window, filled, table_config.time_column, selected_value_column)
    compared_points = int(error_metrics.pop("compared_points"))
    status = "passed" if compared_points == gap_length and missing_after == 0 else "failed"
    message = (
        ""
        if status == "passed"
        else f"compared {compared_points}/{gap_length} removed points, missing_after={missing_after}"
    )

    result = DatabaseHoldoutResult(
        run_id=run_id,
        job_name=job.job_name,
        source_schema=job.source_schema,
        target_schema=job.target_schema,
        table_name=table_config.table_name,
        value_column=selected_value_column,
        group_key=selected_group_key,
        method=effective_config.method,
        fault_type=fault_type,
        gap_start_time=pd.Timestamp(truth_window[table_config.time_column].iloc[0]),
        gap_end_time=pd.Timestamp(truth_window[table_config.time_column].iloc[-1]),
        gap_length_periods=gap_length,
        expected_points=gap_length,
        compared_points=compared_points,
        actual_filled=actual_filled,
        missing_after=missing_after,
        mean_absolute_error=error_metrics["mean_absolute_error"],
        root_mean_squared_error=error_metrics["root_mean_squared_error"],
        max_absolute_error=error_metrics["max_absolute_error"],
        mean_absolute_percentage_error=error_metrics["mean_absolute_percentage_error"],
        status=status,
        message=message,
        checked_at=checked_at,
    )
    series = _series_for_database_holdout(
        result,
        truth,
        faulted,
        filled,
        table_config.time_column,
        selected_value_column,
        start_position,
        gap_length,
    )

    if persist:
        write_database_holdout_result(engine, job, result, series)

    return result, series


def write_database_holdout_result(
    engine: Engine,
    job: GapfillJobConfig,
    result: DatabaseHoldoutResult,
    series: pd.DataFrame,
) -> None:
    ensure_control_tables(engine, job.target_schema)
    result_row = {
        "run_id": result.run_id,
        "job_name": result.job_name,
        "source_schema": result.source_schema,
        "target_schema": result.target_schema,
        "table_name": result.table_name,
        "value_column": result.value_column,
        "group_key": result.group_key,
        "method": result.method,
        "fault_type": result.fault_type,
        "gap_start_time": result.gap_start_time.to_pydatetime(),
        "gap_end_time": result.gap_end_time.to_pydatetime(),
        "gap_length_periods": result.gap_length_periods,
        "expected_points": result.expected_points,
        "compared_points": result.compared_points,
        "actual_filled": result.actual_filled,
        "missing_after": result.missing_after,
        "mean_absolute_error": result.mean_absolute_error,
        "root_mean_squared_error": result.root_mean_squared_error,
        "max_absolute_error": result.max_absolute_error,
        "mean_absolute_percentage_error": result.mean_absolute_percentage_error,
        "status": result.status,
        "message": result.message,
        "checked_at": result.checked_at.to_pydatetime(),
    }

    with engine.begin() as conn:
        pd.DataFrame([result_row]).to_sql(
            "gapfill_holdout_results",
            con=conn,
            schema=job.target_schema,
            if_exists="append",
            index=False,
        )
        series.to_sql(
            "gapfill_holdout_series",
            con=conn,
            schema=job.target_schema,
            if_exists="append",
            index=False,
            chunksize=10_000,
        )


def _select_table_config(job: GapfillJobConfig, table_name: str) -> TimeSeriesTableConfig:
    for table_config in job.tables:
        if table_config.table_name == table_name:
            return table_config
    raise ValueError(f"Unknown gapfill table '{table_name}' in job '{job.job_name}'.")


def _validate_gap_length(gap_length_periods: int, table_config: TimeSeriesTableConfig) -> int:
    try:
        gap_length = int(gap_length_periods)
    except (TypeError, ValueError) as exc:
        raise ValueError("gap_length_periods must be an integer.") from exc

    if gap_length < 1:
        raise ValueError("gap_length_periods must be at least 1.")
    if gap_length > table_config.max_gap_periods:
        raise ValueError(f"gap_length_periods must be at most {table_config.max_gap_periods} for {table_config.table_name}.")
    return gap_length


def _override_method(table_config: TimeSeriesTableConfig, method: str | None) -> str:
    if method is None or not str(method).strip():
        return table_config.method
    method_value = str(method).strip()
    if method_value not in GAPFILL_METHODS:
        raise ValueError(f"method must be one of: {', '.join(GAPFILL_METHODS)}")
    return method_value


def _read_holdout_source(
    engine: Engine,
    job: GapfillJobConfig,
    table_config: TimeSeriesTableConfig,
    value_column: str,
    read_start: pd.Timestamp,
    read_end: pd.Timestamp,
    group_key: str | None,
) -> pd.DataFrame:
    if not table_exists(engine, job.source_schema, table_config.table_name):
        raise ValueError(f"source table {job.source_schema}.{table_config.table_name} does not exist.")

    columns = tuple(dict.fromkeys((table_config.time_column, value_column, *table_config.groupby_columns)))
    select_columns = ", ".join(quote_identifier(column) for column in columns)
    time_column = quote_identifier(table_config.time_column)
    where_parts = [
        f"{time_column} >= :read_start",
        f"{time_column} <= :read_end",
    ]
    params: dict[str, Any] = {
        "read_start": read_start.to_pydatetime(),
        "read_end": read_end.to_pydatetime(),
    }

    group_values = _parse_group_key(group_key)
    for index, (column, value) in enumerate(group_values.items()):
        if column not in table_config.groupby_columns:
            raise ValueError(f"group_key column '{column}' is not configured for {table_config.table_name}.")
        key = f"group_{index}"
        where_parts.append(f"{quote_identifier(column)}::text = :{key}")
        params[key] = value

    with engine.connect() as conn:
        dataframe = pd.read_sql(
            text(f"""
                SELECT {select_columns}
                FROM {qualified(job.source_schema, table_config.table_name)}
                WHERE {" AND ".join(where_parts)}
                ORDER BY {time_column}
            """),
            conn,
            params=params,
        )

    if dataframe.empty:
        raise ValueError("No source rows found for the selected holdout window.")

    dataframe[table_config.time_column] = pd.to_datetime(dataframe[table_config.time_column], utc=True)
    return dataframe


def _select_holdout_group(
    source: pd.DataFrame,
    table_config: TimeSeriesTableConfig,
    value_column: str,
    gap_start_time: pd.Timestamp,
    gap_length: int,
    requested_group_key: str | None,
) -> tuple[pd.DataFrame, str, int]:
    candidates: list[tuple[str, pd.DataFrame]] = []
    if table_config.groupby_columns:
        for _, group in source.groupby(list(table_config.groupby_columns), dropna=False):
            row = group.iloc[0]
            group_values = {column: row[column] for column in table_config.groupby_columns}
            candidates.append((group_key_from_values(table_config.groupby_columns, group_values), group.copy()))
    else:
        candidates.append(("__all__", source.copy()))

    candidates.sort(key=lambda item: len(item[1]), reverse=True)
    requested = requested_group_key.strip() if requested_group_key else None
    for candidate_key, candidate in candidates:
        if requested and candidate_key != requested:
            continue
        selected = candidate.sort_values(table_config.time_column).reset_index(drop=True)
        start_position = _find_start_position(selected, table_config.time_column, gap_start_time)
        if start_position is None or start_position + gap_length > len(selected):
            continue
        truth_window = selected.iloc[start_position : start_position + gap_length]
        if truth_window[value_column].isna().any():
            raise ValueError("The selected holdout segment already contains missing values and cannot be used as truth.")
        return selected, candidate_key, start_position

    if requested:
        raise ValueError(f"No eligible rows found for group_key '{requested}' at the selected start and length.")
    raise ValueError("No eligible group has enough rows at the selected start and length.")


def _find_start_position(
    dataframe: pd.DataFrame,
    time_column: str,
    gap_start_time: pd.Timestamp,
) -> int | None:
    times = pd.to_datetime(dataframe[time_column], utc=True)
    matching_positions = np.flatnonzero(times >= _timestamp(gap_start_time))
    if len(matching_positions) == 0:
        return None
    return int(matching_positions[0])


def _inject_fault(
    truth: pd.DataFrame,
    gap_start_index: int,
    gap_length_periods: int,
    value_column: str,
    fault_type: str,
) -> pd.DataFrame:
    faulted = truth.copy()
    window_index = faulted.index[gap_start_index : gap_start_index + gap_length_periods]
    if fault_type == "timestamp_gap":
        return faulted.drop(index=window_index).reset_index(drop=True)

    faulted.loc[window_index, value_column] = np.nan
    return faulted


def _calculate_error(
    truth_window: pd.DataFrame,
    filled: pd.DataFrame,
    time_column: str,
    value_column: str,
) -> dict[str, float | int | None]:
    joined = truth_window[[time_column, value_column]].rename(columns={value_column: "expected"}).merge(
        filled[[time_column, value_column]].rename(columns={value_column: "actual"}),
        on=time_column,
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
    mape = (
        float((absolute_errors[non_zero_expected] / comparable.loc[non_zero_expected, "expected"].abs()).mean() * 100.0)
        if non_zero_expected.any()
        else None
    )
    return {
        "compared_points": int(len(comparable)),
        "mean_absolute_error": float(absolute_errors.mean()),
        "root_mean_squared_error": float(np.sqrt(np.square(errors).mean())),
        "max_absolute_error": float(absolute_errors.max()),
        "mean_absolute_percentage_error": mape,
    }


def _series_for_database_holdout(
    result: DatabaseHoldoutResult,
    truth: pd.DataFrame,
    faulted: pd.DataFrame,
    filled: pd.DataFrame,
    time_column: str,
    value_column: str,
    gap_start_index: int,
    gap_length_periods: int,
) -> pd.DataFrame:
    truth_series = truth[[time_column, value_column]].copy()
    truth_series["series_name"] = "truth"
    truth_series["was_filled"] = False

    source_display = truth[[time_column, value_column]].copy()
    source_window = source_display.index[gap_start_index : gap_start_index + gap_length_periods]
    source_display.loc[source_window, value_column] = np.nan
    source_display["series_name"] = "source"
    source_display["was_filled"] = False

    if not faulted[time_column].equals(source_display[time_column]):
        faulted_lookup = faulted.set_index(time_column)[value_column]
        source_display[value_column] = source_display[time_column].map(faulted_lookup)

    filled_series = filled[[time_column, value_column, "gapfill_filled_columns"]].copy()
    filled_series["series_name"] = "gapfilled"
    filled_series["was_filled"] = filled_series["gapfill_filled_columns"].astype(str).str.contains(value_column, regex=False)
    filled_series = filled_series.drop(columns=["gapfill_filled_columns"])

    output = pd.concat([truth_series, source_display, filled_series], ignore_index=True)
    output = output.rename(columns={time_column: "time", value_column: "value"})
    output["run_id"] = result.run_id
    output["table_name"] = result.table_name
    output["value_column"] = result.value_column
    output["group_key"] = result.group_key
    output["checked_at"] = result.checked_at.to_pydatetime()
    return output[["run_id", "table_name", "value_column", "group_key", "time", "series_name", "value", "was_filled", "checked_at"]]


def _parse_group_key(group_key: str | None) -> dict[str, str]:
    if not group_key:
        return {}
    values: dict[str, str] = {}
    for token in group_key.split("|"):
        if "=" not in token:
            raise ValueError("group_key must use the format column=value|column=value.")
        column, value = token.split("=", 1)
        column = column.strip()
        if not column:
            raise ValueError("group_key contains an empty column name.")
        values[column] = value.strip()
    return values


def _timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
