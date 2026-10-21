# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stable import surface for reusable OEDS gapfill helpers."""

from .config import (
    BUILTIN_GAPFILL_TABLES_BY_JOB,
    DEFAULT_POSTRUN_TABLES,
    ENTSOE_FMS_TABLES,
    load_job_from_crawler_config,
    select_tables,
)
from .core import (
    GAPFILL_METHODS,
    GroupMetric,
    SeriesFillConfig,
    TableFillResult,
    fill_table,
    infer_frequency,
)
from .selftest import (
    HoldoutTestResult,
    SelfTestCase,
    SelfTestResult,
    list_holdout_datasets,
    list_self_test_cases,
    run_holdout_test,
    run_self_tests,
    write_self_test_results,
)

__all__ = [
    "BUILTIN_GAPFILL_TABLES_BY_JOB",
    "DEFAULT_POSTRUN_TABLES",
    "ENTSOE_FMS_TABLES",
    "GAPFILL_METHODS",
    "GroupMetric",
    "HoldoutTestResult",
    "SelfTestCase",
    "SelfTestResult",
    "SeriesFillConfig",
    "TableFillResult",
    "fill_table",
    "infer_frequency",
    "list_holdout_datasets",
    "list_self_test_cases",
    "load_job_from_crawler_config",
    "run_holdout_test",
    "run_self_tests",
    "select_tables",
    "write_self_test_results",
]
