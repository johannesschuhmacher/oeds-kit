# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from oeds_post_scripts.runtime_env import resolve_database_uri
from oeds_gapfill.core import GAPFILL_METHODS, GapfillMethod, SeriesFillConfig


@dataclass(frozen=True)
class TimeSeriesTableConfig:
    table_name: str
    time_column: str
    value_columns: tuple[str, ...]
    groupby_columns: tuple[str, ...]
    update_time_column: str | None = "UpdateTime(UTC)"
    method: GapfillMethod = "donor_refined"
    resolution: pd.Timedelta | None = None
    period: pd.Timedelta = pd.Timedelta(hours=24)
    candidate_periods: tuple[pd.Timedelta, ...] | None = None
    donor_context_periods: int = 6
    donor_search_radius: pd.Timedelta = pd.Timedelta(days=28)
    refinement_periods: int = 3
    max_gap_periods: int = 24
    min_points: int = 3

    def to_series_config(self) -> SeriesFillConfig:
        return SeriesFillConfig(
            table_name=self.table_name,
            time_column=self.time_column,
            value_columns=self.value_columns,
            groupby_columns=self.groupby_columns,
            method=self.method,
            resolution=self.resolution,
            period=self.period,
            candidate_periods=self.candidate_periods,
            donor_context_periods=self.donor_context_periods,
            donor_search_radius=self.donor_search_radius,
            refinement_periods=self.refinement_periods,
            max_gap_periods=self.max_gap_periods,
            min_points=self.min_points,
        )


@dataclass(frozen=True)
class GapfillJobConfig:
    job_name: str
    database_uri: str
    source_schema: str
    target_schema: str
    enabled: bool
    tables: tuple[TimeSeriesTableConfig, ...]
    lookback: pd.Timedelta = pd.Timedelta(days=7)
    fail_on_table_error: bool = True


ENTSOE_FMS_TABLES: tuple[TimeSeriesTableConfig, ...] = (
    TimeSeriesTableConfig(
        table_name="ActualTotalLoad",
        time_column="DateTime(UTC)",
        value_columns=("TotalLoad[MW]",),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode"),
    ),
    TimeSeriesTableConfig(
        table_name="DayAheadTotalLoadForecast",
        time_column="DateTime(UTC)",
        value_columns=("TotalLoad[MW]",),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode"),
    ),
    TimeSeriesTableConfig(
        table_name="AggregatedGenerationPerType",
        time_column="DateTime(UTC)",
        value_columns=("ActualGenerationOutput[MW]", "ActualConsumption[MW]"),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode", "ProductionType"),
    ),
    TimeSeriesTableConfig(
        table_name="DayAheadAggregatedGeneration",
        time_column="DateTime(UTC)",
        value_columns=("GenerationForecast[MW]", "ScheduledConsumption[MW]"),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode"),
    ),
    TimeSeriesTableConfig(
        table_name="GenerationForecastsForWindAndSolar",
        time_column="DateTime(UTC)",
        value_columns=(
            "DayAheadGenerationForecast[MW]",
            "IntradayGenerationForecast[MW]",
            "CurrentGenerationForecast[MW]",
        ),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode", "ProductionType"),
    ),
    TimeSeriesTableConfig(
        table_name="EnergyPrices",
        time_column="DateTime(UTC)",
        value_columns=("Price[Currency/MWh]",),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode", "ContractType", "Sequence", "Currency"),
    ),
    TimeSeriesTableConfig(
        table_name="ForecastedTransferCapacities",
        time_column="DateTime(UTC)",
        value_columns=("ForecastTransferCapacity[MW]",),
        groupby_columns=(
            "ResolutionCode",
            "OutAreaCode",
            "OutAreaDisplayName",
            "OutAreaTypeCode",
            "OutAreaMapCode",
            "InAreaCode",
            "InAreaDisplayName",
            "InAreaTypeCode",
            "InAreaMapCode",
            "ContractType",
        ),
    ),
    TimeSeriesTableConfig(
        table_name="PhysicalFlows",
        time_column="DateTime(UTC)",
        value_columns=("Flow[MW]",),
        groupby_columns=(
            "ResolutionCode",
            "OutAreaCode",
            "OutAreaDisplayName",
            "OutAreaTypeCode",
            "OutAreaMapCode",
            "InAreaCode",
            "InAreaDisplayName",
            "InAreaTypeCode",
            "InAreaMapCode",
        ),
    ),
    TimeSeriesTableConfig(
        table_name="TotalLoadForecast",
        time_column="DateTime(UTC)",
        value_columns=("MinimumLoadForecast[MW]", "MaximumLoadForecast[MW]"),
        groupby_columns=("ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode", "ContractType"),
    ),
)


DEFAULT_POSTRUN_TABLES = (
    "ActualTotalLoad",
    "DayAheadTotalLoadForecast",
    "GenerationForecastsForWindAndSolar",
    "EnergyPrices",
    "ForecastedTransferCapacities",
    "PhysicalFlows",
)

BUILTIN_GAPFILL_TABLES_BY_JOB: dict[str, tuple[TimeSeriesTableConfig, ...]] = {
    "entsoe_fms": ENTSOE_FMS_TABLES,
}


def load_job_from_crawler_config(
    config_path: Path,
    job_name: str = "entsoe_fms",
    table_names: list[str] | None = None,
) -> GapfillJobConfig:
    with config_path.open(encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    default_config = raw_config.get("default", {})
    crawler_config = {**default_config, **raw_config.get(job_name, {})}
    gapfill_config = crawler_config.get("gapfill") or {}

    source_schema = str(crawler_config.get("schema_name", job_name))
    target_schema = str(gapfill_config.get("target_schema", f"{source_schema}_gapfilled"))
    database_uri = _database_uri_for_schema(crawler_config, default_config, source_schema)
    enabled = bool(gapfill_config.get("enable", True))
    method = gapfill_config.get("method", "donor_refined")
    table_methods = _parse_table_methods(gapfill_config.get("table_methods"))
    max_gap_periods = int(gapfill_config.get("max_gap_periods", 24))
    candidate_periods = _parse_timedelta_tuple(gapfill_config.get("candidate_periods"))
    donor_context_periods = int(gapfill_config.get("donor_context_periods", 6))
    donor_search_radius = _parse_timedelta(gapfill_config.get("donor_search_radius", "28d"))
    refinement_periods = int(gapfill_config.get("refinement_periods", 3))
    lookback = _parse_timedelta(gapfill_config.get("lookback", "7d"))
    fail_on_table_error = bool(gapfill_config.get("fail_on_table_error", True))

    if table_names is not None:
        selected = table_names
    elif "tables" in gapfill_config:
        selected = list(gapfill_config.get("tables") or [])
    else:
        selected = list(DEFAULT_POSTRUN_TABLES)
    tables = select_tables(
        selected,
        method=method,
        table_methods=table_methods,
        max_gap_periods=max_gap_periods,
        candidate_periods=candidate_periods,
        donor_context_periods=donor_context_periods,
        donor_search_radius=donor_search_radius,
        refinement_periods=refinement_periods,
    )

    return GapfillJobConfig(
        job_name=job_name,
        database_uri=database_uri,
        source_schema=source_schema,
        target_schema=target_schema,
        enabled=enabled,
        tables=tuple(tables),
        lookback=lookback,
        fail_on_table_error=fail_on_table_error,
    )


def select_tables(
    table_names: list[str] | tuple[str, ...],
    *,
    method: str = "donor_refined",
    table_methods: dict[str, str] | None = None,
    max_gap_periods: int = 24,
    candidate_periods: tuple[pd.Timedelta, ...] | None = None,
    donor_context_periods: int = 6,
    donor_search_radius: pd.Timedelta = pd.Timedelta(days=28),
    refinement_periods: int = 3,
) -> list[TimeSeriesTableConfig]:
    known_tables = {table.table_name: table for table in ENTSOE_FMS_TABLES}
    configured_methods = table_methods or {}
    selected: list[TimeSeriesTableConfig] = []
    for table_name in table_names:
        if table_name not in known_tables:
            raise ValueError(f"Unknown gapfill table '{table_name}'. Known tables: {sorted(known_tables)}")
        table_method = configured_methods.get(table_name, method)
        selected.append(
            replace(
                known_tables[table_name],
                method=_validate_method(table_method),
                max_gap_periods=max_gap_periods,
                candidate_periods=candidate_periods,
                donor_context_periods=donor_context_periods,
                donor_search_radius=donor_search_radius,
                refinement_periods=refinement_periods,
            )
        )
    return selected


def _parse_table_methods(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(table_name): str(method)
        for table_name, method in value.items()
        if str(table_name).strip() and str(method).strip()
    }


def _database_uri_for_schema(crawler_config: dict[str, Any], default_config: dict[str, Any], source_schema: str) -> str:
    database_uri = str(crawler_config.get("database_uri") or default_config.get("database_uri"))
    resolved = resolve_database_uri(database_uri)
    if resolved.endswith("search_path="):
        return f"{resolved}{source_schema}"
    return resolved


def _parse_timedelta(value: object) -> pd.Timedelta:
    if isinstance(value, pd.Timedelta):
        return value
    if isinstance(value, int | float):
        return pd.Timedelta(hours=float(value))
    return pd.Timedelta(_normalize_timedelta_text(str(value)))


def _normalize_timedelta_text(value: str) -> str:
    """Normalize user-facing duration strings before passing them to pandas."""
    return re.sub(r"(?<=\d)\s*d\b", "D", value.strip(), flags=re.IGNORECASE)


def _parse_timedelta_tuple(value: object) -> tuple[pd.Timedelta, ...] | None:
    if value is None:
        return None
    if isinstance(value, str | int | float | pd.Timedelta):
        values = [value]
    else:
        values = list(value)  # type: ignore[arg-type]
    return tuple(_parse_timedelta(item) for item in values)


def _validate_method(method: str) -> GapfillMethod:
    if method not in GAPFILL_METHODS:
        methods = ", ".join(GAPFILL_METHODS)
        raise ValueError(f"gapfill method must be one of: {methods}")
    return method  # type: ignore[return-value]
