# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd
from scripts.lib.gapfiller.config import GapfillJobConfig, TimeSeriesTableConfig
from scripts.lib.gapfiller.core import GroupMetric, fill_table
from sqlalchemy import Engine, text

CONTROL_TABLES = (
    "gapfill_runs",
    "gapfill_metrics",
    "gapfill_tracking",
    "gapfill_test_results",
    "gapfill_test_series",
    "gapfill_holdout_results",
    "gapfill_holdout_series",
)


@dataclass(frozen=True)
class TrackingState:
    last_source_timestamp: pd.Timestamp | None
    last_update_time: pd.Timestamp | None


@dataclass(frozen=True)
class WindowInfo:
    read_start: pd.Timestamp
    read_end: pd.Timestamp
    changed_start: pd.Timestamp
    changed_end: pd.Timestamp
    max_update_time: pd.Timestamp | None
    changed_rows: int


@dataclass(frozen=True)
class GapfillRunSummary:
    run_id: str
    status: str
    tables_processed: int
    tables_skipped: int
    tables_failed: int
    groups_processed: int
    rows_read: int
    rows_written: int
    missing_before: int
    missing_after: int
    values_filled: int
    message: str


def run_gapfill_job(
    engine: Engine,
    job: GapfillJobConfig,
    *,
    dry_run: bool = False,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    logger: logging.Logger | None = None,
) -> GapfillRunSummary:
    logger = logger or logging.getLogger(__name__)
    run_id = str(uuid.uuid4())
    started_at = pd.Timestamp.now(tz="UTC")

    ensure_control_tables(engine, job.target_schema)
    record_run_start(engine, job, run_id, started_at, dry_run=dry_run)

    if not job.enabled:
        summary = GapfillRunSummary(run_id, "skipped", 0, len(job.tables), 0, 0, 0, 0, 0, 0, 0, "Gapfill job disabled.")
        record_run_finish(engine, job.target_schema, summary, "Gapfill job disabled.")
        return summary

    totals = {
        "tables_processed": 0,
        "tables_skipped": 0,
        "tables_failed": 0,
        "groups_processed": 0,
        "rows_read": 0,
        "rows_written": 0,
        "missing_before": 0,
        "missing_after": 0,
        "values_filled": 0,
    }
    errors: list[str] = []

    for table_config in job.tables:
        try:
            result = process_table(
                engine,
                job,
                table_config,
                run_id,
                started_at,
                dry_run=dry_run,
                start=start,
                end=end,
                logger=logger,
            )
        except Exception as exc:
            totals["tables_failed"] += 1
            errors.append(f"{table_config.table_name}: {exc}")
            logger.exception("Gapfill failed for table %s", table_config.table_name)
            write_metrics(
                engine,
                job,
                run_id,
                [
                    skipped_metric(
                        table_config,
                        status="error",
                        error_message=str(exc),
                    )
                ],
                recorded_at=started_at,
            )
            if job.fail_on_table_error:
                continue
            continue

        if result["status"] == "processed":
            totals["tables_processed"] += 1
        elif result["status"] == "skipped":
            totals["tables_skipped"] += 1
        else:
            totals["tables_failed"] += 1

        for key in ("groups_processed", "rows_read", "rows_written", "missing_before", "missing_after", "values_filled"):
            totals[key] += int(result.get(key, 0))

    status = "success"
    if totals["tables_failed"]:
        status = "failed" if job.fail_on_table_error else "partial"
    message = "; ".join(errors) if errors else "Gapfill run completed."

    summary = GapfillRunSummary(
        run_id=run_id,
        status=status,
        tables_processed=totals["tables_processed"],
        tables_skipped=totals["tables_skipped"],
        tables_failed=totals["tables_failed"],
        groups_processed=totals["groups_processed"],
        rows_read=totals["rows_read"],
        rows_written=totals["rows_written"],
        missing_before=totals["missing_before"],
        missing_after=totals["missing_after"],
        values_filled=totals["values_filled"],
        message=message,
    )
    record_run_finish(engine, job.target_schema, summary, message)
    return summary


def process_table(
    engine: Engine,
    job: GapfillJobConfig,
    table_config: TimeSeriesTableConfig,
    run_id: str,
    run_timestamp: pd.Timestamp,
    *,
    dry_run: bool,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    logger: logging.Logger,
) -> dict[str, int | str]:
    if not table_exists(engine, job.source_schema, table_config.table_name):
        logger.info("Skipping missing source table %s.%s", job.source_schema, table_config.table_name)
        write_metrics(
            engine,
            job,
            run_id,
            [skipped_metric(table_config, status="skipped_source_missing")],
            recorded_at=run_timestamp,
        )
        return {"status": "skipped"}

    source_columns = get_table_columns(engine, job.source_schema, table_config.table_name)
    missing_columns = sorted(set(required_columns(table_config)) - set(source_columns))
    if missing_columns:
        raise ValueError(f"source table is missing configured columns: {missing_columns}")

    tracking = get_tracking_state(engine, job.target_schema, job.source_schema, table_config.table_name)
    window = get_processing_window(engine, job, table_config, tracking, source_columns, start=start, end=end)
    if window is None:
        logger.info("No changed rows for %s.%s", job.source_schema, table_config.table_name)
        write_metrics(
            engine,
            job,
            run_id,
            [skipped_metric(table_config, status="skipped_no_changes")],
            recorded_at=run_timestamp,
        )
        return {"status": "skipped"}

    source = read_source_window(engine, job.source_schema, table_config.table_name, table_config.time_column, window)
    if source.empty:
        write_metrics(
            engine,
            job,
            run_id,
            [skipped_metric(table_config, status="skipped_empty_window")],
            recorded_at=run_timestamp,
        )
        return {"status": "skipped"}

    fill_result = fill_table(source, table_config.to_series_config(), run_id, run_timestamp)
    metrics = fill_result.metrics

    if not dry_run:
        replace_target_window(
            engine,
            job.target_schema,
            table_config.table_name,
            table_config.time_column,
            window.read_start,
            window.read_end,
            fill_result.dataframe,
        )
        if start is None and end is None:
            update_tracking_state(
                engine,
                job.target_schema,
                job.source_schema,
                table_config.table_name,
                last_source_timestamp=window.changed_end,
                last_update_time=window.max_update_time,
            )

    write_metrics(engine, job, run_id, metrics, recorded_at=run_timestamp)
    logger.info(
        "Gapfilled %s: %s rows read, %s rows written, %s values filled.",
        table_config.table_name,
        len(source),
        0 if dry_run else len(fill_result.dataframe),
        sum(metric.filled_values for metric in metrics),
    )

    return {
        "status": "processed",
        "groups_processed": len({metric.group_key for metric in metrics}),
        "rows_read": len(source),
        "rows_written": 0 if dry_run else len(fill_result.dataframe),
        "missing_before": sum(metric.missing_before for metric in metrics),
        "missing_after": sum(metric.missing_after for metric in metrics),
        "values_filled": sum(metric.filled_values for metric in metrics),
    }


def ensure_control_tables(engine: Engine, target_schema: str) -> None:
    schema = quote_identifier(target_schema)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_runs (
                run_id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                source_schema TEXT NOT NULL,
                target_schema TEXT NOT NULL,
                status TEXT NOT NULL,
                dry_run BOOLEAN NOT NULL DEFAULT FALSE,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ,
                tables_requested INTEGER NOT NULL DEFAULT 0,
                tables_processed INTEGER NOT NULL DEFAULT 0,
                tables_skipped INTEGER NOT NULL DEFAULT 0,
                tables_failed INTEGER NOT NULL DEFAULT 0,
                groups_processed INTEGER NOT NULL DEFAULT 0,
                rows_read INTEGER NOT NULL DEFAULT 0,
                rows_written INTEGER NOT NULL DEFAULT 0,
                missing_before INTEGER NOT NULL DEFAULT 0,
                missing_after INTEGER NOT NULL DEFAULT 0,
                values_filled INTEGER NOT NULL DEFAULT 0,
                message TEXT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_metrics (
                run_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                source_schema TEXT NOT NULL,
                target_schema TEXT NOT NULL,
                table_name TEXT NOT NULL,
                value_column TEXT NOT NULL,
                group_key TEXT NOT NULL,
                method TEXT NOT NULL,
                source_rows INTEGER NOT NULL,
                output_rows INTEGER NOT NULL,
                expected_rows INTEGER NOT NULL,
                created_gap_rows INTEGER NOT NULL,
                missing_before INTEGER NOT NULL,
                missing_after INTEGER NOT NULL,
                filled_values INTEGER NOT NULL,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                status TEXT NOT NULL,
                error_message TEXT,
                recorded_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_tracking (
                source_schema TEXT NOT NULL,
                table_name TEXT NOT NULL,
                last_source_timestamp TIMESTAMPTZ,
                last_update_time TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (source_schema, table_name)
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_test_results (
                run_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                status TEXT NOT NULL,
                expected_filled INTEGER NOT NULL,
                actual_filled INTEGER NOT NULL,
                missing_after INTEGER NOT NULL,
                message TEXT,
                checked_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_test_series (
                run_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                series_name TEXT NOT NULL,
                value DOUBLE PRECISION,
                is_original BOOLEAN NOT NULL,
                was_filled BOOLEAN NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_holdout_results (
                run_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                source_schema TEXT NOT NULL,
                target_schema TEXT NOT NULL,
                table_name TEXT NOT NULL,
                value_column TEXT NOT NULL,
                group_key TEXT NOT NULL,
                method TEXT NOT NULL,
                fault_type TEXT NOT NULL,
                gap_start_time TIMESTAMPTZ NOT NULL,
                gap_end_time TIMESTAMPTZ NOT NULL,
                gap_length_periods INTEGER NOT NULL,
                expected_points INTEGER NOT NULL,
                compared_points INTEGER NOT NULL,
                actual_filled INTEGER NOT NULL,
                missing_after INTEGER NOT NULL,
                mean_absolute_error DOUBLE PRECISION,
                root_mean_squared_error DOUBLE PRECISION,
                max_absolute_error DOUBLE PRECISION,
                mean_absolute_percentage_error DOUBLE PRECISION,
                status TEXT NOT NULL,
                message TEXT,
                checked_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {schema}.gapfill_holdout_series (
                run_id TEXT NOT NULL,
                table_name TEXT NOT NULL,
                value_column TEXT NOT NULL,
                group_key TEXT NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                series_name TEXT NOT NULL,
                value DOUBLE PRECISION,
                was_filled BOOLEAN NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL
            )
        """))


def record_run_start(
    engine: Engine,
    job: GapfillJobConfig,
    run_id: str,
    started_at: pd.Timestamp,
    *,
    dry_run: bool,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO {qualified(job.target_schema, "gapfill_runs")}
                    (run_id, job_name, source_schema, target_schema, status, dry_run, started_at, tables_requested)
                VALUES
                    (:run_id, :job_name, :source_schema, :target_schema, 'running', :dry_run, :started_at, :tables_requested)
            """),
            {
                "run_id": run_id,
                "job_name": job.job_name,
                "source_schema": job.source_schema,
                "target_schema": job.target_schema,
                "dry_run": dry_run,
                "started_at": started_at.to_pydatetime(),
                "tables_requested": len(job.tables),
            },
        )


def record_run_finish(
    engine: Engine,
    target_schema: str,
    summary: GapfillRunSummary,
    message: str,
) -> None:
    finished_at = pd.Timestamp.now(tz="UTC")
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                UPDATE {qualified(target_schema, "gapfill_runs")}
                SET status = :status,
                    finished_at = :finished_at,
                    tables_processed = :tables_processed,
                    tables_skipped = :tables_skipped,
                    tables_failed = :tables_failed,
                    groups_processed = :groups_processed,
                    rows_read = :rows_read,
                    rows_written = :rows_written,
                    missing_before = :missing_before,
                    missing_after = :missing_after,
                    values_filled = :values_filled,
                    message = :message
                WHERE run_id = :run_id
            """),
            {
                "run_id": summary.run_id,
                "status": summary.status,
                "finished_at": finished_at.to_pydatetime(),
                "tables_processed": summary.tables_processed,
                "tables_skipped": summary.tables_skipped,
                "tables_failed": summary.tables_failed,
                "groups_processed": summary.groups_processed,
                "rows_read": summary.rows_read,
                "rows_written": summary.rows_written,
                "missing_before": summary.missing_before,
                "missing_after": summary.missing_after,
                "values_filled": summary.values_filled,
                "message": message,
            },
        )


def write_metrics(
    engine: Engine,
    job: GapfillJobConfig,
    run_id: str,
    metrics: list[GroupMetric],
    *,
    recorded_at: pd.Timestamp,
) -> None:
    rows = []
    for metric in metrics:
        rows.append({
            "run_id": run_id,
            "job_name": job.job_name,
            "source_schema": job.source_schema,
            "target_schema": job.target_schema,
            "table_name": metric.table_name,
            "value_column": metric.value_column,
            "group_key": metric.group_key,
            "method": metric.method,
            "source_rows": metric.source_rows,
            "output_rows": metric.output_rows,
            "expected_rows": metric.expected_rows,
            "created_gap_rows": metric.created_gap_rows,
            "missing_before": metric.missing_before,
            "missing_after": metric.missing_after,
            "filled_values": metric.filled_values,
            "start_time": _to_datetime(metric.start_time),
            "end_time": _to_datetime(metric.end_time),
            "status": metric.status,
            "error_message": metric.error_message,
            "recorded_at": recorded_at.to_pydatetime(),
        })

    if not rows:
        return

    with engine.begin() as conn:
        pd.DataFrame(rows).to_sql(
            "gapfill_metrics",
            con=conn,
            schema=job.target_schema,
            if_exists="append",
            index=False,
            chunksize=10_000,
        )


def get_processing_window(
    engine: Engine,
    job: GapfillJobConfig,
    config: TimeSeriesTableConfig,
    tracking: TrackingState,
    source_columns: list[str],
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> WindowInfo | None:
    update_column = config.update_time_column if config.update_time_column in source_columns else None
    schema_table = qualified(job.source_schema, config.table_name)
    time_column = quote_identifier(config.time_column)

    where_parts = [f"{time_column} IS NOT NULL"]
    params: dict[str, Any] = {}

    if start is not None:
        where_parts.append(f"{time_column} >= :manual_start")
        params["manual_start"] = start.to_pydatetime()
    if end is not None:
        where_parts.append(f"{time_column} <= :manual_end")
        params["manual_end"] = end.to_pydatetime()

    if start is None and end is None and update_column and tracking.last_update_time is not None:
        where_parts.append(f"{quote_identifier(update_column)} > :last_update_time")
        params["last_update_time"] = tracking.last_update_time.to_pydatetime()
    elif start is None and end is None and tracking.last_source_timestamp is not None:
        where_parts.append(f"{time_column} > :last_source_timestamp")
        params["last_source_timestamp"] = tracking.last_source_timestamp.to_pydatetime()

    where_clause = " AND ".join(where_parts)
    max_update_expr = f"MAX({quote_identifier(update_column)})" if update_column else "NULL"

    with engine.connect() as conn:
        row = conn.execute(
            text(f"""
                SELECT
                    MIN({time_column}) AS changed_start,
                    MAX({time_column}) AS changed_end,
                    {max_update_expr} AS max_update_time,
                    COUNT(*) AS changed_rows
                FROM {schema_table}
                WHERE {where_clause}
            """),
            params,
        ).mappings().one()

    changed_rows = int(row["changed_rows"] or 0)
    if changed_rows == 0 or row["changed_start"] is None or row["changed_end"] is None:
        return None

    changed_start = _timestamp_or_none(row["changed_start"])
    changed_end = _timestamp_or_none(row["changed_end"])
    if changed_start is None or changed_end is None:
        return None
    max_update_time = _timestamp_or_none(row["max_update_time"])

    read_start = changed_start
    if start is None and end is None and (tracking.last_source_timestamp is not None or tracking.last_update_time is not None):
        read_start = changed_start - job.lookback

    return WindowInfo(
        read_start=read_start,
        read_end=changed_end,
        changed_start=changed_start,
        changed_end=changed_end,
        max_update_time=max_update_time,
        changed_rows=changed_rows,
    )


def read_source_window(
    engine: Engine,
    source_schema: str,
    table_name: str,
    time_column: str,
    window: WindowInfo,
) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(
            text(f"""
                SELECT *
                FROM {qualified(source_schema, table_name)}
                WHERE {quote_identifier(time_column)} >= :read_start
                  AND {quote_identifier(time_column)} <= :read_end
                ORDER BY {quote_identifier(time_column)}
            """),
            conn,
            params={
                "read_start": window.read_start.to_pydatetime(),
                "read_end": window.read_end.to_pydatetime(),
            },
        )


def replace_target_window(
    engine: Engine,
    target_schema: str,
    table_name: str,
    time_column: str,
    read_start: pd.Timestamp,
    read_end: pd.Timestamp,
    dataframe: pd.DataFrame,
) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(target_schema)}"))
        if table_exists(engine, target_schema, table_name):
            ensure_target_columns(engine, target_schema, table_name, dataframe)
            conn.execute(
                text(f"""
                    DELETE FROM {qualified(target_schema, table_name)}
                    WHERE {quote_identifier(time_column)} >= :read_start
                      AND {quote_identifier(time_column)} <= :read_end
                """),
                {
                    "read_start": read_start.to_pydatetime(),
                    "read_end": read_end.to_pydatetime(),
                },
            )

        dataframe.to_sql(
            table_name,
            con=conn,
            schema=target_schema,
            if_exists="append",
            index=False,
            chunksize=10_000,
        )


def ensure_target_columns(engine: Engine, target_schema: str, table_name: str, dataframe: pd.DataFrame) -> None:
    existing = set(get_table_columns(engine, target_schema, table_name))
    additions = [column for column in dataframe.columns if column not in existing]
    if not additions:
        return

    with engine.begin() as conn:
        for column in additions:
            conn.execute(
                text(f"""
                    ALTER TABLE {qualified(target_schema, table_name)}
                    ADD COLUMN {quote_identifier(column)} {_sql_type_for_series(dataframe[column])}
                """)
            )


def get_tracking_state(engine: Engine, target_schema: str, source_schema: str, table_name: str) -> TrackingState:
    with engine.connect() as conn:
        row = conn.execute(
            text(f"""
                SELECT last_source_timestamp, last_update_time
                FROM {qualified(target_schema, "gapfill_tracking")}
                WHERE source_schema = :source_schema
                  AND table_name = :table_name
            """),
            {"source_schema": source_schema, "table_name": table_name},
        ).mappings().fetchone()

    if row is None:
        return TrackingState(last_source_timestamp=None, last_update_time=None)
    return TrackingState(
        last_source_timestamp=_timestamp_or_none(row["last_source_timestamp"]),
        last_update_time=_timestamp_or_none(row["last_update_time"]),
    )


def update_tracking_state(
    engine: Engine,
    target_schema: str,
    source_schema: str,
    table_name: str,
    *,
    last_source_timestamp: pd.Timestamp,
    last_update_time: pd.Timestamp | None,
) -> None:
    updated_at = pd.Timestamp.now(tz="UTC")
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO {qualified(target_schema, "gapfill_tracking")}
                    (source_schema, table_name, last_source_timestamp, last_update_time, updated_at)
                VALUES
                    (:source_schema, :table_name, :last_source_timestamp, :last_update_time, :updated_at)
                ON CONFLICT (source_schema, table_name)
                DO UPDATE SET
                    last_source_timestamp = EXCLUDED.last_source_timestamp,
                    last_update_time = EXCLUDED.last_update_time,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                "source_schema": source_schema,
                "table_name": table_name,
                "last_source_timestamp": last_source_timestamp.to_pydatetime(),
                "last_update_time": None if last_update_time is None else last_update_time.to_pydatetime(),
                "updated_at": updated_at.to_pydatetime(),
            },
        )


def skipped_metric(
    config: TimeSeriesTableConfig,
    *,
    status: str,
    error_message: str | None = None,
) -> GroupMetric:
    return GroupMetric(
        table_name=config.table_name,
        value_column=",".join(config.value_columns),
        group_key="__table__",
        method=config.method,
        source_rows=0,
        output_rows=0,
        expected_rows=0,
        created_gap_rows=0,
        missing_before=0,
        missing_after=0,
        filled_values=0,
        start_time=None,
        end_time=None,
        status=status,
        error_message=error_message,
    )


def required_columns(config: TimeSeriesTableConfig) -> tuple[str, ...]:
    columns = [config.time_column, *config.value_columns, *config.groupby_columns]
    return tuple(dict.fromkeys(columns))


def table_exists(engine: Engine, schema: str, table_name: str) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                      AND table_name = :table_name
                )
            """),
            {"schema": schema, "table_name": table_name},
        ).scalar())


def get_table_columns(engine: Engine, schema: str, table_name: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = :table_name
                ORDER BY ordinal_position
            """),
            {"schema": schema, "table_name": table_name},
        ).all()
    return [str(row[0]) for row in rows]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified(schema: str, table_name: str) -> str:
    return f"{quote_identifier(schema)}.{quote_identifier(table_name)}"


def _timestamp_or_none(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _to_datetime(value: pd.Timestamp | None) -> Any:
    if value is None:
        return None
    return pd.Timestamp(value).to_pydatetime()


def _sql_type_for_series(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE PRECISION"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMPTZ"
    return "TEXT"
