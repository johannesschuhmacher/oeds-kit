from __future__ import annotations

import glob
import io
import json
import os
import sqlite3
import subprocess
import threading
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crawler.common.crawler_utils import CrawlerSkipped
from crawler.common.runtime_env import resolve_database_uri
from oeds_scheduler_ui.locks import LOCK_KEY_PREFIX, CrawlerLock, lock_engine
from oeds_scheduler_ui.planner import CrawlerJobConfig, SchedulerJobPlan, job_plan
from oeds_scheduler_ui.runtime import CrawlerJobRunner, last_log_line
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from crawler_admin import POST_INSTALLED
from crawler_admin.config_service import (
    CrawlerOverview,
    get_config_path,
    get_crawler_overview,
    get_repo_root,
)
from crawler_admin.gapfill_service import _connect_args_for_database_uri

# Last line CrawlerJobRunner writes to a scheduler run log.
SCHEDULER_LOG_FOOTER = "# finished: "


@dataclass(frozen=True)
class ActionOption:
    value: str
    label: str


@dataclass(frozen=True)
class ActionField:
    name: str
    label: str
    input_type: str
    required: bool = False
    help_text: str | None = None
    placeholder: str | None = None
    options: list[ActionOption] = field(default_factory=list)
    default_value: Any = None
    min_value: int | None = None
    max_value: int | None = None


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    label: str
    description: str
    button_label: str
    fields: list[ActionField] = field(default_factory=list)
    note: str | None = None


@dataclass(frozen=True)
class RunRecord:
    run_id: int
    crawler_name: str
    action_id: str
    action_label: str
    trigger_source: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    log_path: str
    summary: str | None
    error_message: str | None
    config_overrides: dict[str, Any]
    action_payload: dict[str, Any]

    @property
    def is_active(self) -> bool:
        return self.status in {"queued", "running"}


@dataclass(frozen=True)
class ActionRuntimeBenchmark:
    action_id: str
    action_label: str
    sample_count: int
    success_count: int
    failure_count: int
    success_rate: float
    latest_seconds: float | None
    latest_finished_at: str | None


@dataclass(frozen=True)
class PreparedAction:
    crawler_name: str
    action_id: str
    action_label: str
    description: str
    effective_config: dict[str, Any]
    config_overrides: dict[str, Any]
    action_payload: dict[str, Any]
    # Receives the open run log; returns the summary line.
    executor: Callable[[io.TextIOBase], str | None]


@dataclass(frozen=True)
class SchedulerRun:
    """A scheduler run, read from ``logs/runs/<crawler>-<job>-<YYYYmmdd-HHMMSS>.log``.

    Carries the RunRecord fields the pages show, so either can be the latest run.
    """

    job_name: str
    created_at: str  # start as naive UTC ISO, like RunRecord.created_at
    status: str  # from the log footer; "running" while there is none
    log_path: str

    @property
    def action_label(self) -> str:
        return f"Scheduler {self.job_name}"


def read_scheduler_run(path: Path, crawler_name: str) -> SchedulerRun:
    """Parse the name and footer of a log written by ``CrawlerJobRunner``."""

    # The name holds the job id (":" -> "-") and the scheduler's local start time;
    # the admin runs in the same image and time zone.
    stem = path.stem.removeprefix(f"{crawler_name}-")
    started_at = datetime.strptime(stem[-15:], "%Y%m%d-%H%M%S").astimezone(UTC)
    last_line = last_log_line(path) or ""
    status = (
        last_line.removeprefix(SCHEDULER_LOG_FOOTER)
        if last_line.startswith(SCHEDULER_LOG_FOOTER)
        else "running"
    )
    return SchedulerRun(stem[:-16], started_at.strftime("%Y-%m-%dT%H:%M:%S"), status, str(path))


def running_crawlers(database_uri: str | None, crawler_names: list[str]) -> set[str] | None:
    """Crawlers whose run lock (``oeds_scheduler_ui.locks``) a scheduler or admin holds.

    Read-only lookup in pg_locks: a bigint advisory key appears as classid (high
    half) and objid (low half) with objsubid 1. None when the database is unknown
    or not reachable.
    """

    if not database_uri:
        return None
    try:
        resolved_uri = resolve_database_uri(database_uri)
        engine = create_engine(
            resolved_uri,
            poolclass=NullPool,
            connect_args=_connect_args_for_database_uri(resolved_uri),
        )
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT crawler_name
                    FROM unnest(CAST(:names AS text[])) AS names(crawler_name)
                    WHERE EXISTS (
                        SELECT 1
                        FROM pg_locks
                        WHERE locktype = 'advisory' AND granted AND objsubid = 1
                          AND ((classid::bigint << 32) | objid::bigint)
                              = hashtext(:prefix || crawler_name)::bigint
                    )
                    """
                ),
                {"names": list(crawler_names), "prefix": LOCK_KEY_PREFIX},
            )
            return {str(row[0]) for row in rows}
    except Exception:
        return None


def tail_log_lines(log_path: Path, lines: int) -> list[str]:
    """Last ``lines`` lines of a log, reading only its end."""

    tail_bytes = lines * 1024
    with log_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        start = max(0, handle.tell() - tail_bytes)
        handle.seek(start)
        content = handle.read().decode("utf-8", errors="replace").splitlines()
    if start:
        content = content[1:]  # the first line is cut
    return content[-lines:]


class ActionValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("Action validation failed.")
        self.errors = errors


class LockError(Exception):
    pass


class CrawlerRunService:
    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or get_repo_root()
        self.state_dir = self._resolve_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.state_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "runs.sqlite3"
        self._guard = threading.Lock()
        self._active_runs: dict[str, int] = {}
        self._active_threads: dict[int, threading.Thread] = {}
        self._init_db()
        self._mark_interrupted_runs()

    def _resolve_state_dir(self) -> Path:
        explicit_dir = os.getenv("OEDS_ADMIN_STATE_DIR")
        if explicit_dir:
            return Path(explicit_dir)

        if os.name == "nt":
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                return Path(local_app_data) / "OEDS" / "crawler-admin"

        return Path.home() / ".oeds-crawler-admin"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS crawler_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crawler_name TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    action_label TEXT NOT NULL,
                    trigger_source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_seconds REAL,
                    log_path TEXT NOT NULL,
                    summary TEXT,
                    error_message TEXT,
                    config_overrides_json TEXT NOT NULL,
                    action_payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_crawler_runs_name_created
                ON crawler_runs (crawler_name, created_at DESC)
                """
            )
            connection.commit()

    def _mark_interrupted_runs(self) -> None:
        timestamp = self._utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE crawler_runs
                SET status = 'interrupted',
                    finished_at = COALESCE(finished_at, ?),
                    summary = COALESCE(summary, 'Admin service restarted while the run was active.'),
                    error_message = COALESCE(error_message, 'Admin service restarted while the run was active.')
                WHERE status IN ('queued', 'running')
                """,
                (timestamp,),
            )
            connection.commit()

    def list_runs(
        self, crawler_name: str | None = None, limit: int = 20
    ) -> list[RunRecord]:
        query = """
            SELECT *
            FROM crawler_runs
        """
        parameters: list[Any] = []

        if crawler_name:
            query += " WHERE crawler_name = ?"
            parameters.append(crawler_name)

        query += " ORDER BY run_id DESC LIMIT ?"
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM crawler_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        return self._row_to_record(row) if row else None

    def get_latest_runs_map(self) -> dict[str, RunRecord]:
        records = self.list_runs(limit=200)
        latest_by_crawler: dict[str, RunRecord] = {}
        for record in records:
            latest_by_crawler.setdefault(record.crawler_name, record)
        return latest_by_crawler

    def get_runtime_benchmarks(
        self,
        crawler_name: str,
        limit: int = 100,
    ) -> list[ActionRuntimeBenchmark]:
        records = [
            record
            for record in self.list_runs(crawler_name, limit=limit)
            if record.duration_seconds is not None
            and not record.is_active
            and record.status != "skipped"
        ]
        grouped_records: dict[str, list[RunRecord]] = {}
        for record in records:
            grouped_records.setdefault(record.action_id, []).append(record)

        benchmarks: list[ActionRuntimeBenchmark] = []
        for action_id, action_records in grouped_records.items():
            success_records = [
                record for record in action_records if record.status == "succeeded"
            ]
            latest_record = action_records[0]
            sample_count = len(action_records)
            success_count = len(success_records)
            failure_count = sample_count - success_count
            success_rate = (
                round(success_count / sample_count * 100.0, 1) if sample_count else 0.0
            )

            benchmarks.append(
                ActionRuntimeBenchmark(
                    action_id=action_id,
                    action_label=latest_record.action_label,
                    sample_count=sample_count,
                    success_count=success_count,
                    failure_count=failure_count,
                    success_rate=success_rate,
                    latest_seconds=latest_record.duration_seconds,
                    latest_finished_at=latest_record.finished_at,
                )
            )

        return benchmarks

    def get_latest_scheduler_run(self, crawler_name: str) -> SchedulerRun | None:
        """Newest run log the scheduler wrote under ``<repo root>/logs/runs``."""

        pattern = f"{glob.escape(crawler_name)}-*-????????-??????.log"
        paths = (self.repo_root / "logs" / "runs").glob(pattern)
        newest = max(paths, key=lambda path: path.name[-19:], default=None)
        return read_scheduler_run(newest, crawler_name) if newest else None

    def get_active_run(self, crawler_name: str) -> RunRecord | None:
        with self._guard:
            run_id = self._active_runs.get(crawler_name)
        if run_id is None:
            return None
        return self.get_run(run_id)

    def is_locked(self, crawler_name: str) -> bool:
        with self._guard:
            return crawler_name in self._active_runs

    def start_action(
        self,
        crawler_name: str,
        action_id: str,
        action_payload: dict[str, Any],
    ) -> int:
        prepared = self.prepare_action(crawler_name, action_id, action_payload)

        with self._guard:
            if crawler_name in self._active_runs:
                raise LockError(f"Crawler '{crawler_name}' already has an active run.")

            lock = self._acquire_crawler_lock(prepared)
            try:
                run_id = self._create_run_record(prepared)
                self._active_runs[crawler_name] = run_id

                thread = threading.Thread(
                    target=self._execute_run,
                    args=(run_id, prepared, lock),
                    daemon=True,
                    name=f"crawler-run-{crawler_name}-{run_id}",
                )
                self._active_threads[run_id] = thread
                thread.start()
            except Exception:
                lock.release()
                raise

        return run_id

    def _acquire_crawler_lock(self, prepared: PreparedAction) -> CrawlerLock:
        """Take the crawler's advisory lock shared with the scheduler daemon."""

        database_uri = prepared.effective_config.get(
            "database_uri"
        ) or prepared.effective_config.get("db_uri")
        if not database_uri:
            raise ActionValidationError(
                ["database_uri is not configured; the run lock needs it."]
            )
        lock = CrawlerLock.try_acquire(lock_engine(database_uri), prepared.crawler_name)
        if lock is None:
            raise LockError(
                f"Crawler '{prepared.crawler_name}' is already running "
                "(scheduler or another admin session)."
            )
        return lock

    def prepare_action(
        self,
        crawler_name: str,
        action_id: str,
        action_payload: dict[str, Any],
    ) -> PreparedAction:
        overview = get_crawler_overview(crawler_name, self.repo_root)
        if overview.card is None:
            raise ActionValidationError([f"Unknown crawler '{crawler_name}'."])

        if not overview.raw_config:
            raise ActionValidationError(
                [
                    f"Crawler '{crawler_name}' has no section in CRAWLER_CONFIG.yml and cannot be started from the admin UI."
                ]
            )

        definitions = {
            definition.action_id: definition
            for definition in self.get_action_definitions(overview)
        }
        definition = definitions.get(action_id)
        if definition is None:
            raise ActionValidationError(
                [f"Unknown action '{action_id}' for crawler '{crawler_name}'."]
            )

        effective_config = dict(overview.effective_config)

        if action_id == "run_now":
            plan = self._crawler_plan(crawler_name, effective_config)
            return PreparedAction(
                crawler_name=crawler_name,
                action_id=action_id,
                action_label=definition.label,
                description="One-off manual run with the current YAML configuration. Scheduler settings stay unchanged.",
                effective_config=effective_config,
                config_overrides={},
                action_payload={},
                executor=lambda log: self._run_oeds_crawl(plan, log),
            )

        if action_id == "gapfill_backfill":
            from oeds_gapfill.config import BUILTIN_GAPFILL_TABLES_BY_JOB

            supported_tables = BUILTIN_GAPFILL_TABLES_BY_JOB.get(crawler_name, ())
            if not supported_tables:
                raise ActionValidationError(
                    [
                        f"Crawler '{crawler_name}' does not have built-in gapfill table metadata."
                    ]
                )

            start_value = self._require_text(
                action_payload.get("gapfill_start"), "Gapfill start"
            )
            end_value = str(action_payload.get("gapfill_end") or "").strip()
            start_timestamp = self._parse_timestamp(start_value, "Gapfill start")
            end_timestamp = (
                self._parse_timestamp(end_value, "Gapfill end") if end_value else None
            )
            if end_timestamp is not None and end_timestamp < start_timestamp:
                raise ActionValidationError(
                    ["Gapfill end must not be earlier than gapfill start."]
                )

            selected_tables = self._ensure_list(action_payload.get("gapfill_tables"))
            valid_tables = {table.table_name for table in supported_tables}
            invalid_tables = sorted(set(selected_tables) - valid_tables)
            if invalid_tables:
                raise ActionValidationError(
                    [f"Unknown gapfill table(s): {', '.join(invalid_tables)}."]
                )

            payload = {
                "job": crawler_name,
                "start": start_value,
                "end": end_value,
                "tables": selected_tables,
            }
            description = f"Gapfill backfill for {crawler_name} from {start_value}"
            if end_value:
                description += f" to {end_value}"

            return PreparedAction(
                crawler_name=crawler_name,
                action_id=action_id,
                action_label=definition.label,
                description=description + ".",
                effective_config=effective_config,
                config_overrides={},
                action_payload=payload,
                executor=lambda log: self._run_gapfill_backfill(payload, log),
            )

        if action_id == "price_forecast":
            if crawler_name != "entsoe_api":
                raise ActionValidationError(
                    ["Price forecast can only be started from the entsoe_api crawler."]
                )

            run_mode = str(action_payload.get("run_mode") or "forecast").strip().lower()
            if run_mode not in {"forecast", "self_test"}:
                raise ActionValidationError(["Price forecast run mode is invalid."])

            target_date = str(action_payload.get("target_date") or "").strip()
            if target_date:
                self._parse_date(target_date, "Target date")
            train_days = self._parse_int(
                action_payload.get("train_days"),
                field_label="Train days",
                minimum=14,
                maximum=365,
            )
            backtest_days = self._parse_int(
                action_payload.get("backtest_days"),
                field_label="Backtest days",
                minimum=0,
                maximum=60,
            )

            payload = {
                "run_mode": run_mode,
                "target_date": target_date,
                "train_days": train_days,
                "backtest_days": backtest_days,
            }
            description = (
                "Price forecast self-test"
                if run_mode == "self_test"
                else "Price forecast run"
            )
            if target_date:
                description += f" for {target_date}"

            return PreparedAction(
                crawler_name=crawler_name,
                action_id=action_id,
                action_label=definition.label,
                description=description + ".",
                effective_config=effective_config,
                config_overrides={},
                action_payload=payload,
                executor=lambda log: self._run_price_forecast(payload, log),
            )

        raise ActionValidationError(
            [f"No runtime handler registered for action '{action_id}'."]
        )

    def get_action_definitions(
        self, overview: CrawlerOverview
    ) -> list[ActionDefinition]:
        effective_config = overview.effective_config
        actions = [
            ActionDefinition(
                action_id="run_now",
                label="Run once",
                description="Execute the crawler immediately as a one-off manual run. The YAML schedule is not changed.",
                button_label="Start one-off run",
            )
        ]

        # The price forecast and gapfill actions shell out to ``oeds-post``.
        if POST_INSTALLED and overview.crawler_name == "entsoe_api":
            actions.append(
                ActionDefinition(
                    action_id="price_forecast",
                    label="Price forecast",
                    description="Run the day-ahead price forecast post-run workflow on demand.",
                    button_label="Start price forecast",
                    note="The normal scheduled path runs oeds-post forecast day-ahead-price through post_run_scripts.",
                    fields=[
                        ActionField(
                            name="run_mode",
                            label="Run mode",
                            input_type="select",
                            required=True,
                            options=[
                                ActionOption(
                                    value="forecast", label="Database forecast"
                                ),
                                ActionOption(value="self_test", label="Self-test"),
                            ],
                            default_value="forecast",
                        ),
                        ActionField(
                            name="target_date",
                            label="Target date",
                            input_type="text",
                            placeholder="2026-05-23",
                            help_text="Leave empty to forecast tomorrow in Europe/Berlin.",
                            default_value="",
                        ),
                        ActionField(
                            name="train_days",
                            label="Train days",
                            input_type="number",
                            required=True,
                            min_value=14,
                            max_value=365,
                            default_value=self._env_int_default(
                                "OEDS_PRICE_FORECAST_TRAIN_DAYS", 56
                            ),
                        ),
                        ActionField(
                            name="backtest_days",
                            label="Backtest days",
                            input_type="number",
                            required=True,
                            min_value=0,
                            max_value=60,
                            default_value=self._env_int_default(
                                "OEDS_PRICE_FORECAST_BACKTEST_DAYS", 2
                            ),
                        ),
                    ],
                )
            )

        supported_gapfill_tables = ()
        if POST_INSTALLED:
            from oeds_gapfill.config import BUILTIN_GAPFILL_TABLES_BY_JOB

            supported_gapfill_tables = BUILTIN_GAPFILL_TABLES_BY_JOB.get(
                overview.crawler_name, ()
            )
        if supported_gapfill_tables:
            gapfill_config = effective_config.get("gapfill")
            configured_tables = []
            if isinstance(gapfill_config, dict) and isinstance(
                gapfill_config.get("tables"), list
            ):
                configured_tables = [
                    str(table_name)
                    for table_name in gapfill_config.get("tables", [])
                    if str(table_name).strip()
                ]
            actions.append(
                ActionDefinition(
                    action_id="gapfill_backfill",
                    label="Gapfill backfill",
                    description="Run the configured gapfill process for an explicit source time window.",
                    button_label="Start gapfill backfill",
                    note="Uses the current gapfill settings and writes to the configured target schema. It does not run the crawler first.",
                    fields=[
                        ActionField(
                            name="gapfill_start",
                            label="Start timestamp",
                            input_type="text",
                            required=True,
                            placeholder="2024-01-01 or 2024-01-01T00:00:00Z",
                            help_text="First source timestamp to process. Date-only values are treated as UTC midnight.",
                        ),
                        ActionField(
                            name="gapfill_end",
                            label="End timestamp (optional)",
                            input_type="text",
                            placeholder="2024-12-31 or 2024-12-31T23:00:00Z",
                            help_text="Leave empty to process through the latest available source timestamp.",
                        ),
                        ActionField(
                            name="gapfill_tables",
                            label="Tables (optional)",
                            input_type="multiselect",
                            options=[
                                ActionOption(
                                    value=table.table_name, label=table.table_name
                                )
                                for table in supported_gapfill_tables
                            ],
                            help_text="Leave empty to use the tables selected in the current gapfill configuration.",
                            default_value=configured_tables,
                        ),
                    ],
                )
            )

        return actions

    def get_run_log_tail(self, run_id: int, lines: int = 200) -> dict[str, Any]:
        record = self.get_run(run_id)
        if record is None:
            return {
                "text": "",
                "line_count": 0,
                "status": "missing",
                "summary": None,
                "error_message": "Run not found.",
            }

        log_path = Path(record.log_path)
        if not log_path.exists():
            return {
                "text": "",
                "line_count": 0,
                "status": record.status,
                "summary": record.summary,
                "error_message": record.error_message,
            }

        # Polled every few seconds while a run is active.
        tail_lines = tail_log_lines(log_path, lines)
        return {
            "text": "\n".join(tail_lines),
            "line_count": len(tail_lines),
            "status": record.status,
            "summary": record.summary,
            "error_message": record.error_message,
        }

    def _create_run_record(self, prepared: PreparedAction) -> int:
        created_at = self._utc_now()
        placeholder_name = f"run-pending-{prepared.crawler_name}-{created_at.replace(':', '').replace('-', '')}.log"
        placeholder_path = str((self.logs_dir / placeholder_name).resolve())

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawler_runs (
                    crawler_name,
                    action_id,
                    action_label,
                    trigger_source,
                    status,
                    created_at,
                    log_path,
                    config_overrides_json,
                    action_payload_json
                )
                VALUES (?, ?, ?, 'manual', 'queued', ?, ?, ?, ?)
                """,
                (
                    prepared.crawler_name,
                    prepared.action_id,
                    prepared.action_label,
                    created_at,
                    placeholder_path,
                    json.dumps(prepared.config_overrides, ensure_ascii=True),
                    json.dumps(prepared.action_payload, ensure_ascii=True),
                ),
            )
            run_id = int(cursor.lastrowid)
            final_log_path = str(
                (self.logs_dir / f"{prepared.crawler_name}-{run_id}.log").resolve()
            )
            connection.execute(
                "UPDATE crawler_runs SET log_path = ? WHERE run_id = ?",
                (final_log_path, run_id),
            )
            connection.commit()

        return run_id

    def _execute_run(
        self, run_id: int, prepared: PreparedAction, lock: CrawlerLock | None = None
    ) -> None:
        started_at = self._utc_now()
        log_path = Path(self.get_run(run_id).log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                "UPDATE crawler_runs SET status = 'running', started_at = ? WHERE run_id = ?",
                (started_at, run_id),
            )
            connection.commit()

        summary = prepared.description
        error_message: str | None = None
        status = "succeeded"

        try:
            with log_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(f"[RUN] {prepared.action_label}\n")
                handle.write(f"[CRAWLER] {prepared.crawler_name}\n")
                handle.write(f"[STARTED] {started_at}\n")
                if prepared.action_payload:
                    payload = json.dumps(prepared.action_payload, ensure_ascii=True, indent=2)
                    handle.write(f"[PAYLOAD] {payload}\n")
                # The executors hand the log to subprocesses.
                handle.flush()
                result_summary = prepared.executor(handle)
                if result_summary:
                    summary = result_summary
                handle.write("[RESULT] Run completed.\n")
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            with log_path.open("a", encoding="utf-8", newline="") as handle:
                if isinstance(exc, CrawlerSkipped):
                    status = "skipped"
                    summary = message
                    handle.write(f"\n[SKIPPED] {message}\n")
                else:
                    status = "failed"
                    error_message = message
                    summary = f"{prepared.action_label} failed."
                    handle.write("\n[TRACEBACK]\n")
                    handle.write(traceback.format_exc())
        finally:
            if lock is not None:
                lock.release()
            finished_at = self._utc_now()
            duration_seconds = self._duration_seconds(started_at, finished_at)

            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE crawler_runs
                    SET status = ?,
                        finished_at = ?,
                        duration_seconds = ?,
                        summary = ?,
                        error_message = ?
                    WHERE run_id = ?
                    """,
                    (
                        status,
                        finished_at,
                        duration_seconds,
                        summary,
                        error_message,
                        run_id,
                    ),
                )
                connection.commit()

            with self._guard:
                self._active_runs.pop(prepared.crawler_name, None)
                self._active_threads.pop(run_id, None)

    def _crawler_plan(
        self, crawler_name: str, effective_config: dict[str, Any]
    ) -> SchedulerJobPlan:
        """Scheduler plan for the crawler section itself (no named job)."""

        try:
            return job_plan(
                CrawlerJobConfig(crawler_name, "default", effective_config, None)
            )
        except ValueError as exc:
            raise ActionValidationError([str(exc)]) from exc

    def _run_oeds_crawl(self, plan: SchedulerJobPlan, handle: io.TextIOBase) -> str | None:
        """Run the crawler and its post-run commands with the scheduler's runner.

        The ``oeds-crawl`` child and the post-run commands write straight to
        the run log, so their output cannot interleave with other runs.
        """

        handle.flush()
        result = CrawlerJobRunner(get_config_path(self.repo_root)).run(
            plan, log_path=Path(handle.name)
        )
        if result.status == "skipped":
            raise CrawlerSkipped(result.error)
        if result.status == "failed":
            if result.error:
                raise RuntimeError(result.error)
            failed = [
                f"'{post_run.command}' ({post_run.error})"
                for post_run in result.post_run_results
                if not post_run.success
            ]
            raise RuntimeError("Post-run command failed: " + ", ".join(failed))
        return "Run completed successfully."

    def _run_gapfill_backfill(
        self, payload: dict[str, Any], handle: io.TextIOBase
    ) -> str | None:
        command = [
            "oeds-post",
            "gapfill",
            "entsoe-fms",
            "--job",
            str(payload["job"]),
            "--start",
            str(payload["start"]),
        ]
        if payload.get("end"):
            command.extend(["--end", str(payload["end"])])
        if payload.get("tables"):
            command.extend(
                ["--tables", ",".join(str(table) for table in payload["tables"])]
            )

        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Gapfill backfill exited with code {completed.returncode}."
            )

        if payload.get("end"):
            return f"Gapfill backfill completed for {payload['job']} from {payload['start']} to {payload['end']}."
        return (
            f"Gapfill backfill completed for {payload['job']} from {payload['start']}."
        )

    def _run_price_forecast(
        self, payload: dict[str, Any], handle: io.TextIOBase
    ) -> str | None:
        command = [
            "oeds-post",
            "forecast",
            "day-ahead-price",
            "--train-days",
            str(payload["train_days"]),
            "--backtest-days",
            str(payload["backtest_days"]),
        ]
        if payload.get("target_date"):
            command.extend(["--target-date", str(payload["target_date"])])
        if payload.get("run_mode") == "self_test":
            command.append("--self-test")

        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Price forecast exited with code {completed.returncode}."
            )

        if payload.get("run_mode") == "self_test":
            return "Price forecast self-test completed."
        if payload.get("target_date"):
            return f"Price forecast completed for {payload['target_date']}."
        return "Price forecast completed."

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=int(row["run_id"]),
            crawler_name=str(row["crawler_name"]),
            action_id=str(row["action_id"]),
            action_label=str(row["action_label"]),
            trigger_source=str(row["trigger_source"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_seconds=float(row["duration_seconds"])
            if row["duration_seconds"] is not None
            else None,
            log_path=str(row["log_path"]),
            summary=row["summary"],
            error_message=row["error_message"],
            config_overrides=json.loads(row["config_overrides_json"] or "{}"),
            action_payload=json.loads(row["action_payload_json"] or "{}"),
        )

    def _parse_int(
        self,
        value: Any,
        *,
        field_label: str,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        raw_value = str(value or "").strip()
        if not raw_value:
            raise ActionValidationError([f"{field_label} is required."])

        try:
            parsed = int(raw_value)
        except ValueError as exc:
            raise ActionValidationError([f"{field_label} must be an integer."]) from exc

        if minimum is not None and parsed < minimum:
            raise ActionValidationError([f"{field_label} must be at least {minimum}."])
        if maximum is not None and parsed > maximum:
            raise ActionValidationError([f"{field_label} must be at most {maximum}."])

        return parsed

    def _require_text(self, value: Any, field_label: str) -> str:
        text_value = str(value or "").strip()
        if not text_value:
            raise ActionValidationError([f"{field_label} is required."])
        return text_value

    def _parse_timestamp(self, value: str, field_label: str) -> datetime:
        text_value = value.strip()
        try:
            return datetime.fromisoformat(text_value.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError as exc:
            raise ActionValidationError(
                [f"{field_label} must be a valid ISO date or timestamp."]
            ) from exc

    def _parse_date(self, value: str, field_label: str) -> datetime:
        text_value = value.strip()
        try:
            return datetime.fromisoformat(text_value)
        except ValueError as exc:
            raise ActionValidationError(
                [f"{field_label} must be a valid ISO date."]
            ) from exc

    def _env_int_default(self, name: str, fallback: int) -> int:
        try:
            return int(os.getenv(name, str(fallback)))
        except ValueError:
            return fallback

    def _ensure_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text_value = str(value).strip()
        return [text_value] if text_value else []

    def _duration_seconds(self, started_at: str, finished_at: str) -> float:
        start_dt = datetime.fromisoformat(started_at)
        finish_dt = datetime.fromisoformat(finished_at)
        return round((finish_dt - start_dt).total_seconds(), 3)

    def _utc_now(self) -> str:
        # Naive UTC ISO timestamps, the format stored in existing run records.
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
