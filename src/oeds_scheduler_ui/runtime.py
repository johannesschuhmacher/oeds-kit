"""Runtime execution helpers for planned scheduler jobs.

A scheduled run is an ``oeds-crawl`` subprocess (provided by the crawler pack)
whose output goes to its own file under ``logs/runs/``. Exit code 0 means
succeeded, 3 skipped, anything else failed.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Sequence, TextIO

from oeds_scheduler_ui.locks import CrawlerLock
from oeds_scheduler_ui.planner import SchedulerJobPlan

logger = logging.getLogger(__name__)

EXIT_SKIPPED = 3
DEFAULT_MAX_PARALLEL_RUNS = 3
DEFAULT_KEEP_RUN_LOGS = 200


@dataclass(frozen=True)
class PostRunCommandResult:
    """Result of one scheduler-owned post-run command."""

    command: str
    returncode: int | None
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class CrawlerRunResult:
    """Result of executing one planned crawler job."""

    job_id: str
    display_name: str
    crawler_name: str
    job_name: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    crawler_success: bool
    post_run_success: bool
    success: bool
    status: str  # "succeeded" | "failed" | "skipped"
    crawler_result: Any = None
    error: str | None = None
    post_run_results: tuple[PostRunCommandResult, ...] = ()
    log_path: Path | None = None


@dataclass(frozen=True)
class ScheduledCrawlerJob:
    """Runtime queue item created from a dry scheduler plan."""

    plan: SchedulerJobPlan
    lock_keys: frozenset[str]

    @property
    def job_id(self) -> str:
        return self.plan.job_id

    @property
    def display_name(self) -> str:
        return self.plan.display_name


@dataclass(frozen=True)
class QueuedCrawlerJob:
    """Queued runtime job with scheduling timestamps."""

    job: ScheduledCrawlerJob
    scheduled_for: datetime
    enqueued_at: datetime


PostRunExecutor = Callable[[str, SchedulerJobPlan, TextIO], PostRunCommandResult]


def is_crawler_skipped(exc: BaseException) -> bool:
    """Return whether ``exc`` is a crawler's ``CrawlerSkipped``.

    Matched by class name so the scheduler does not depend on crawler-pack
    internals (``crawler.common.crawler_utils.CrawlerSkipped`` today, possibly
    ``oeds.CrawlerSkipped`` later).
    """

    return any(cls.__name__ == "CrawlerSkipped" for cls in type(exc).__mro__)


def resolve_crawl_command() -> list[str]:
    """argv prefix that starts ``oeds-crawl``.

    ``$OEDS_CRAWL_COMMAND`` (shell-style quoting) wins; otherwise the script
    next to the current interpreter, then ``oeds-crawl`` on ``PATH``.
    """

    configured = os.environ.get("OEDS_CRAWL_COMMAND")
    if configured:
        return shlex.split(configured)
    found = shutil.which(
        "oeds-crawl", path=str(Path(sys.executable).parent)
    ) or shutil.which("oeds-crawl")
    return [found or "oeds-crawl"]


def crawl_command(
    crawler_name: str,
    config_path: str | Path,
    job_name: str | None = None,
    command: Sequence[str] | None = None,
) -> list[str]:
    """Full argv for one ``oeds-crawl`` run; ``--job`` is omitted for the default job."""

    argv = [
        *(command if command is not None else resolve_crawl_command()),
        crawler_name,
        "--config",
        str(config_path),
    ]
    if job_name and job_name != "default":
        argv.extend(["--job", job_name])
    return argv


def run_status_from_returncode(returncode: int) -> str:
    if returncode == 0:
        return "succeeded"
    if returncode == EXIT_SKIPPED:
        return "skipped"
    return "failed"


def last_log_line(path: Path, tail_bytes: int = 16384) -> str | None:
    """Last non-empty line of a (possibly large) log file."""

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - tail_bytes))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if line.strip():
            return line.strip()
    return None


class CrawlerJobRunner:
    """Run planned jobs as ``oeds-crawl`` subprocesses, one log file per run."""

    def __init__(
        self,
        config_path: str | Path,
        *,
        command: Sequence[str] | None = None,
        post_run_executor: PostRunExecutor | None = None,
        logs_dir: str | Path = "logs",
        keep_run_logs: int = DEFAULT_KEEP_RUN_LOGS,
    ) -> None:
        self.config_path = Path(config_path)
        self.command = list(command) if command is not None else resolve_crawl_command()
        self._post_run_executor = post_run_executor or execute_post_command
        # Relative to the working directory, like BaseCrawler's logs/<crawler>.log.
        self.logs_dir = Path(logs_dir)
        self.keep_run_logs = keep_run_logs

    def run(self, plan: SchedulerJobPlan) -> CrawlerRunResult:
        started_at = datetime.now()
        log_path = self._new_run_log_path(plan, started_at)
        argv = crawl_command(
            plan.crawler_name, self.config_path, plan.job_name, self.command
        )
        post_run_results: tuple[PostRunCommandResult, ...] = ()

        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"# {plan.job_id} started {started_at:%Y-%m-%d %H:%M:%S}\n")
            log.write(f"# {' '.join(argv)}\n")
            log.flush()
            status, error = self._run_crawl(argv, plan.run_timeout_seconds, log, log_path)

            if status == "succeeded" and plan.run_post_scripts and plan.post_run_scripts:
                post_run_results = tuple(
                    self._execute_post_run_command(command, plan, log)
                    for command in plan.post_run_scripts
                )
            post_run_success = all(result.success for result in post_run_results)
            if not post_run_success:
                status = "failed"
            log.write(f"# finished: {status}\n")

        # BaseCrawler attaches the SMTP alert handler to the crawler's own
        # logger, so a CRITICAL record there is what sends the failure mail.
        # The traceback is in the child's log file, not here.
        crawler_logger = logging.getLogger(plan.crawler_name)
        if status == "skipped":
            crawler_logger.info("Scheduled run of %s skipped: %s", plan.display_name, error)
        elif error is not None:
            crawler_logger.critical(
                "Scheduled run of %s failed: %s (log: %s)",
                plan.display_name,
                error,
                log_path,
            )

        finished_at = datetime.now()
        crawler_success = error is None
        return CrawlerRunResult(
            job_id=plan.job_id,
            display_name=plan.display_name,
            crawler_name=plan.crawler_name,
            job_name=plan.job_name,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            crawler_success=crawler_success,
            post_run_success=post_run_success,
            success=crawler_success and post_run_success,
            status=status,
            error=error,
            post_run_results=post_run_results,
            log_path=log_path,
        )

    def _run_crawl(
        self,
        argv: Sequence[str],
        timeout: float | None,
        log: TextIO,
        log_path: Path,
    ) -> tuple[str, str | None]:
        """Run the crawler process; return ``(status, error)``."""

        try:
            completed = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "failed", f"timed out after {timeout:g}s; process killed"
        except OSError as exc:
            return "failed", f"cannot start {argv[0]}: {exc}"

        status = run_status_from_returncode(completed.returncode)
        if status == "succeeded":
            return status, None
        detail = last_log_line(log_path)
        if status == "skipped":
            return status, detail or f"exit code {completed.returncode}"
        if detail:
            return status, f"{detail} (exit code {completed.returncode})"
        return status, f"exit code {completed.returncode}"

    def _new_run_log_path(self, plan: SchedulerJobPlan, started_at: datetime) -> Path:
        runs_dir = (self.logs_dir / "runs").resolve()
        runs_dir.mkdir(parents=True, exist_ok=True)
        self._prune_run_logs(runs_dir)
        name = f"{plan.job_id.replace(':', '-')}-{started_at:%Y%m%d-%H%M%S}.log"
        return runs_dir / name

    def _prune_run_logs(self, runs_dir: Path) -> None:
        run_logs = sorted(runs_dir.glob("*.log"), key=lambda path: path.stat().st_mtime)
        excess = len(run_logs) - self.keep_run_logs + 1  # leave room for the new file
        for old_log in run_logs[: max(0, excess)]:
            try:
                old_log.unlink()
            except OSError as exc:
                logger.debug("Could not remove old run log %s: %s", old_log, exc)

    def _execute_post_run_command(
        self,
        command: str,
        plan: SchedulerJobPlan,
        log: TextIO,
    ) -> PostRunCommandResult:
        try:
            return self._post_run_executor(command, plan, log)
        except Exception as exc:  # pragma: no cover - executor is injectable.
            return PostRunCommandResult(
                command=command,
                returncode=None,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )


class CrawlerJobQueue:
    """Queue planned jobs while preventing duplicate and conflicting runs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: deque[QueuedCrawlerJob] = deque()
        self._pending_job_ids: set[str] = set()
        self._active_job_ids: set[str] = set()
        self._active_job_locks: dict[str, frozenset[str]] = {}
        self._active_lock_keys: set[str] = set()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def enqueue(
        self,
        job: ScheduledCrawlerJob,
        scheduled_for: datetime | None = None,
    ) -> bool:
        with self._lock:
            if job.job_id in self._pending_job_ids or job.job_id in self._active_job_ids:
                return False

            self._pending.append(
                QueuedCrawlerJob(
                    job=job,
                    scheduled_for=scheduled_for or datetime.now(),
                    enqueued_at=datetime.now(),
                )
            )
            self._pending_job_ids.add(job.job_id)
            return True

    def pop_ready_jobs(self, limit: int | None = None) -> tuple[QueuedCrawlerJob, ...]:
        """Pop unblocked jobs (at most ``limit``) and mark them active."""

        ready: list[QueuedCrawlerJob] = []
        blocked: deque[QueuedCrawlerJob] = deque()

        with self._lock:
            while self._pending:
                if limit is not None and len(ready) >= limit:
                    blocked.extend(self._pending)
                    self._pending.clear()
                    break
                queued_job = self._pending.popleft()
                job = queued_job.job

                if job.lock_keys & self._active_lock_keys:
                    blocked.append(queued_job)
                    continue

                self._pending_job_ids.remove(job.job_id)
                self._active_job_ids.add(job.job_id)
                self._active_job_locks[job.job_id] = job.lock_keys
                self._active_lock_keys.update(job.lock_keys)
                ready.append(queued_job)

            self._pending = blocked

        return tuple(ready)

    def requeue(self, queued_job: QueuedCrawlerJob) -> None:
        """Put a popped job back for the next tick, keeping its timestamps."""

        with self._lock:
            self._release(queued_job.job)
            if queued_job.job.job_id not in self._pending_job_ids:
                self._pending.append(queued_job)
                self._pending_job_ids.add(queued_job.job.job_id)

    def mark_finished(self, job: ScheduledCrawlerJob) -> None:
        with self._lock:
            self._release(job)

    def _release(self, job: ScheduledCrawlerJob) -> None:
        self._active_job_ids.discard(job.job_id)
        lock_keys = self._active_job_locks.pop(job.job_id, frozenset())
        for lock_key in lock_keys:
            self._active_lock_keys.discard(lock_key)


def execute_post_command(
    command: str,
    plan: SchedulerJobPlan,
    log: TextIO,
) -> PostRunCommandResult:
    """Run one post-run command as a subprocess; its output goes to the run log.

    ``*.py`` paths run with the current interpreter and the working directory
    on ``PYTHONPATH`` (legacy scripts import workspace modules). Anything else,
    such as ``oeds-post gapfill entsoe-fms``, is executed as given.
    """

    argv = shlex.split(command)
    if not argv:
        return PostRunCommandResult(
            command=command,
            returncode=None,
            success=False,
            error="empty post-run command",
        )
    if argv[0].endswith(".py"):
        argv = [sys.executable, *argv]

    log.write(f"# post-run: {command}\n")
    log.flush()
    try:
        completed = subprocess.run(
            argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=_subprocess_env_with_workspace_pythonpath(),
            check=False,
        )
    except OSError as exc:
        return PostRunCommandResult(
            command=command,
            returncode=None,
            success=False,
            error=f"cannot start {argv[0]}: {exc}",
        )
    return PostRunCommandResult(
        command=command,
        returncode=completed.returncode,
        success=completed.returncode == 0,
        error=None if completed.returncode == 0 else f"exit code {completed.returncode}",
    )


def _subprocess_env_with_workspace_pythonpath() -> dict[str, str]:
    env = os.environ.copy()
    workspace = str(Path.cwd())
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join([workspace, existing_pythonpath])
    else:
        env["PYTHONPATH"] = workspace
    return env


def scheduled_job_from_plan(
    plan: SchedulerJobPlan,
    lock_keys: Sequence[str] | None = None,
) -> ScheduledCrawlerJob:
    """Create a runtime queue job from a dry scheduler plan."""

    effective_lock_keys = (
        frozenset(lock_keys) if lock_keys is not None else lock_keys_from_plan(plan)
    )
    return ScheduledCrawlerJob(plan=plan, lock_keys=effective_lock_keys)


def lock_keys_from_plan(plan: SchedulerJobPlan) -> frozenset[str]:
    """Return conservative lock keys without importing crawler modules."""

    configured_lock_keys = plan.raw_config.get("lock_keys")
    if isinstance(configured_lock_keys, str) and configured_lock_keys:
        return frozenset({configured_lock_keys})
    if isinstance(configured_lock_keys, Sequence) and not isinstance(
        configured_lock_keys,
        str,
    ):
        lock_keys = tuple(str(lock_key) for lock_key in configured_lock_keys)
        if lock_keys:
            return frozenset(lock_keys)

    if plan.crawler_name == "entsoe_fms":
        target_data_items = plan.raw_config.get("target_data_items")
        if isinstance(target_data_items, Sequence) and not isinstance(
            target_data_items,
            str,
        ):
            data_item_keys = tuple(str(item) for item in target_data_items)
            if data_item_keys:
                return frozenset(
                    f"{plan.crawler_name}:{data_item}" for data_item in data_item_keys
                )

    return frozenset({f"crawler:{plan.crawler_name}"})


class JobDispatcher:
    """Start queued jobs in background threads, at most ``max_parallel_runs`` at once.

    Each run first takes the crawler's advisory lock when ``lock_engine`` is
    set; a job whose lock is busy stays queued for the next tick. Results of
    finished runs are handed out by the next ``dispatch`` or ``wait`` call.
    The attributes are plain so a config reload can update them while runs
    are active.
    """

    def __init__(
        self,
        queue: CrawlerJobQueue | None = None,
        *,
        runner: Any = None,
        lock_engine: Any = None,
        max_parallel_runs: int = DEFAULT_MAX_PARALLEL_RUNS,
    ) -> None:
        self.queue = queue or CrawlerJobQueue()
        self.runner = runner
        self.lock_engine = lock_engine
        self.max_parallel_runs = max_parallel_runs
        self._guard = Lock()
        self._threads: dict[str, Thread] = {}
        self._finished: list[CrawlerRunResult] = []

    @property
    def active_count(self) -> int:
        with self._guard:
            return len(self._threads)

    @property
    def pending_count(self) -> int:
        return self.queue.pending_count

    def dispatch(self) -> tuple[CrawlerRunResult, ...]:
        """Start ready jobs while slots are free; return results finished since the last call."""

        if self.runner is None:
            raise RuntimeError("dispatcher has no runner")
        with self._guard:
            free_slots = self.max_parallel_runs - len(self._threads)
        if free_slots > 0:
            for queued_job in self.queue.pop_ready_jobs(limit=free_slots):
                self._start(queued_job)
        return self._collect()

    def wait(self, timeout: float | None = None) -> tuple[CrawlerRunResult, ...]:
        """Block until active runs end (or ``timeout``) and return their results."""

        with self._guard:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout)
        return self._collect()

    def _start(self, queued_job: QueuedCrawlerJob) -> None:
        plan = queued_job.job.plan
        lock = None
        if self.lock_engine is not None:
            try:
                lock = CrawlerLock.try_acquire(self.lock_engine, plan.crawler_name)
            except Exception as exc:
                logger.error(
                    "Cannot take the run lock for %s: %s; retrying next tick",
                    plan.display_name,
                    exc,
                )
                self.queue.requeue(queued_job)
                return
            if lock is None:
                logger.info(
                    "%s is already running elsewhere (advisory lock busy); retrying next tick",
                    plan.display_name,
                )
                self.queue.requeue(queued_job)
                return

        thread = Thread(
            target=self._run, args=(queued_job, lock), name=f"run-{plan.job_id}"
        )
        with self._guard:
            self._threads[plan.job_id] = thread
        thread.start()

    def _run(self, queued_job: QueuedCrawlerJob, lock: CrawlerLock | None) -> None:
        plan = queued_job.job.plan
        result: CrawlerRunResult | None = None
        try:
            result = self.runner.run(plan)
        except Exception:
            logger.exception("Run of %s crashed inside the scheduler", plan.display_name)
        finally:
            if lock is not None:
                lock.release()
            self.queue.mark_finished(queued_job.job)
            with self._guard:
                self._threads.pop(plan.job_id, None)
                if result is not None:
                    self._finished.append(result)

    def _collect(self) -> tuple[CrawlerRunResult, ...]:
        with self._guard:
            results = tuple(self._finished)
            self._finished.clear()
        return results
