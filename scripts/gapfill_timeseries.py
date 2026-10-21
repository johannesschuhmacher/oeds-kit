# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = Path(
    os.getenv("OEDS_CRAWLER_CONFIG", ROOT / "CRAWLER_CONFIG.yml")
).expanduser()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oeds_gapfill.config import (
    ENTSOE_FMS_TABLES,
    load_job_from_crawler_config,
)  # noqa: E402
from oeds_gapfill.core import GAPFILL_METHODS  # noqa: E402
from oeds_gapfill.selftest import write_self_test_results  # noqa: E402
from oeds_post_scripts.runtime_env import load_crawler_dotenv  # noqa: E402
from scripts.lib.gapfiller.db import run_gapfill_job  # noqa: E402
from scripts.lib.gapfiller.holdout import run_database_holdout_test  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill gaps in configured OEDS time-series tables.",
    )
    parser.add_argument(
        "--job",
        default="entsoe_fms",
        help="Crawler job name in CRAWLER_CONFIG.yml. Defaults to entsoe_fms.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_FILE,
        help="Path to CRAWLER_CONFIG.yml.",
    )
    parser.add_argument(
        "--tables",
        default=None,
        help="Comma-separated table names. Defaults to the job gapfill.tables config.",
    )
    parser.add_argument(
        "--target-schema",
        default=None,
        help="Override the configured gapfilled target schema.",
    )
    parser.add_argument(
        "--method",
        choices=GAPFILL_METHODS,
        default=None,
        help="Override the configured filling method.",
    )
    parser.add_argument(
        "--max-gap-periods",
        type=int,
        default=None,
        help="Override the maximum contiguous gap length to fill.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process and record metrics without replacing target data.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Manual processing window start timestamp, for example 2024-01-01 or 2024-01-01T00:00:00Z.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Optional manual processing window end timestamp.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run synthetic gapfiller self-tests and write their results for the dashboard.",
    )
    parser.add_argument(
        "--holdout-test",
        action="store_true",
        help="Run a real database holdout test and write results for the Grafana dashboard.",
    )
    parser.add_argument(
        "--holdout-table",
        default=None,
        help="Source table for --holdout-test, for example ActualTotalLoad.",
    )
    parser.add_argument(
        "--holdout-value-column",
        default=None,
        help="Value column for --holdout-test. Defaults to the first configured value column.",
    )
    parser.add_argument(
        "--holdout-group-key",
        default=None,
        help="Optional exact group key, for example AreaCode=10Y1001A1001A83F|ResolutionCode=PT60M.",
    )
    parser.add_argument(
        "--holdout-start",
        default=None,
        help="First timestamp to remove for --holdout-test, for example 2026-04-01T00:00:00Z.",
    )
    parser.add_argument(
        "--holdout-length",
        type=int,
        default=None,
        help="Number of consecutive periods to remove for --holdout-test.",
    )
    parser.add_argument(
        "--holdout-fault-type",
        default="value_gap",
        choices=["value_gap", "timestamp_gap"],
        help="Whether the real-data holdout removes values or timestamps.",
    )
    parser.add_argument(
        "--holdout-context",
        default="28d",
        help="Amount of context to read before and after the holdout start. Defaults to 28d.",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="List built-in time-series table configs and exit.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(message)s",
    )
    logger = logging.getLogger("gapfill_timeseries")

    if args.list_tables:
        for table in ENTSOE_FMS_TABLES:
            print(f"{table.table_name}: {', '.join(table.value_columns)}")
        return 0

    load_crawler_dotenv(ROOT / "crawler" / ".env")
    table_names = (
        [args.holdout_table]
        if args.holdout_test and args.holdout_table
        else _split_tables(args.tables)
    )
    job = load_job_from_crawler_config(
        args.config, job_name=args.job, table_names=table_names
    )
    job = _apply_overrides(job, args)
    manual_start = _parse_optional_timestamp(args.start, "start")
    manual_end = _parse_optional_timestamp(args.end, "end")
    if manual_end is not None and manual_start is None:
        raise ValueError("--start is required when --end is set.")
    if (
        manual_start is not None
        and manual_end is not None
        and manual_end < manual_start
    ):
        raise ValueError("--end must not be earlier than --start.")

    engine = create_engine(job.database_uri)

    if args.holdout_test:
        if not args.holdout_table:
            raise ValueError("--holdout-table is required with --holdout-test.")
        if not args.holdout_start:
            raise ValueError("--holdout-start is required with --holdout-test.")
        if args.holdout_length is None:
            raise ValueError("--holdout-length is required with --holdout-test.")

        result, _ = run_database_holdout_test(
            engine,
            job,
            table_name=args.holdout_table,
            value_column=args.holdout_value_column,
            group_key=args.holdout_group_key,
            gap_start_time=pd.Timestamp(args.holdout_start),
            gap_length_periods=args.holdout_length,
            fault_type=args.holdout_fault_type,
            method=args.method,
            context=pd.Timedelta(args.holdout_context),
            persist=True,
        )
        logger.info(
            "holdout %s: %s.%s %s group=%s compared=%s/%s filled=%s mae=%s rmse=%s",
            result.status,
            result.source_schema,
            result.table_name,
            result.value_column,
            result.group_key,
            result.compared_points,
            result.expected_points,
            result.actual_filled,
            result.mean_absolute_error,
            result.root_mean_squared_error,
        )
        return 0 if result.status == "passed" else 1

    if args.self_test:
        results = write_self_test_results(engine, job)
        for result in results:
            logger.info(
                "self-test %s: %s (%s/%s filled, missing_after=%s)",
                result.test_name,
                result.status,
                result.actual_filled,
                result.expected_filled,
                result.missing_after,
            )
        return 0 if all(result.status == "passed" for result in results) else 1

    if manual_start is not None:
        logger.info(
            "Manual gapfill window requested: start=%s end=%s",
            manual_start,
            manual_end or "latest source timestamp",
        )
    summary = run_gapfill_job(
        engine,
        job,
        dry_run=args.dry_run,
        start=manual_start,
        end=manual_end,
        logger=logger,
    )
    logger.info(
        "Gapfill %s: tables=%s processed, %s skipped, %s failed; rows_written=%s; values_filled=%s",
        summary.status,
        summary.tables_processed,
        summary.tables_skipped,
        summary.tables_failed,
        summary.rows_written,
        summary.values_filled,
    )
    return 0 if summary.status in {"success", "skipped"} else 1


def _apply_overrides(job, args: argparse.Namespace):
    tables = list(job.tables)
    if args.method is not None or args.max_gap_periods is not None:
        tables = [
            replace(
                table,
                method=args.method or table.method,
                max_gap_periods=(
                    args.max_gap_periods
                    if args.max_gap_periods is not None
                    else table.max_gap_periods
                ),
            )
            for table in tables
        ]

    target_schema = args.target_schema or job.target_schema
    return replace(job, tables=tuple(tables), target_schema=target_schema)


def _split_tables(raw_tables: str | None) -> list[str] | None:
    if not raw_tables:
        return None
    return [table.strip() for table in raw_tables.split(",") if table.strip()]


def _parse_optional_timestamp(value: str | None, label: str) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except ValueError as exc:
        raise ValueError(f"--{label} must be a valid timestamp.") from exc
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


if __name__ == "__main__":
    raise SystemExit(main())
