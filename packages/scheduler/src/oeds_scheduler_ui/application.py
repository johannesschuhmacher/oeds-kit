"""Production-oriented scheduler application assembly."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from oeds_scheduler_ui.config import file_signature, load_scheduler_config
from oeds_scheduler_ui.factory import known_crawler_names
from oeds_scheduler_ui.locks import lock_engine
from oeds_scheduler_ui.planner import (
    SchedulerPlanIssue,
    SchedulerPlanResult,
    build_scheduler_job_plans,
)
from oeds_scheduler_ui.runtime import (
    DEFAULT_MAX_PARALLEL_RUNS,
    CrawlerJobRunner,
    CrawlerRunResult,
    JobDispatcher,
    PostRunExecutor,
)
from oeds_scheduler_ui.service import (
    ScheduleFactory,
    SchedulerService,
    SchedulerServiceIssue,
    cron_schedule_factory,
)

try:
    from crawler.common.local_env import apply_email_env_overrides
except ImportError:  # pragma: no cover - crawler pack is optional for the core.
    apply_email_env_overrides = None


logger = logging.getLogger(__name__)

ConfigLoader = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class SchedulerApplicationSnapshot:
    """Observable state after building or reloading the scheduler app."""

    config_path: Path
    crawler_count: int
    planned_job_count: int
    skipped: tuple[SchedulerPlanIssue, ...]
    plan_errors: tuple[SchedulerPlanIssue, ...]
    service_issues: tuple[SchedulerServiceIssue, ...]

    @property
    def ready(self) -> bool:
        return not self.plan_errors and not self.service_issues


class SchedulerApplication:
    """Assemble planning, dispatching, service, and reload handling."""

    def __init__(
        self,
        config_path: str | Path,
        inventory_path: str | Path | None = None,
        workspace_root: str | Path | None = None,
        *,
        schedule_factory: ScheduleFactory = cron_schedule_factory,
        post_run_executor: PostRunExecutor | None = None,
        config_loader: ConfigLoader = load_scheduler_config,
        reference_time: datetime | None = None,
    ) -> None:
        # inventory_path and workspace_root are ignored: crawlers come from the
        # oeds.crawlers entry points. Kept until the deployment stops passing them.
        self.config_path = Path(config_path).resolve()
        self._schedule_factory = schedule_factory
        self._post_run_executor = post_run_executor
        self._config_loader = config_loader
        # The dispatcher outlives reloads so runs that are active during a
        # config change are still tracked and reported.
        self.dispatcher = JobDispatcher()
        self._plan_result: SchedulerPlanResult | None = None
        self._service: SchedulerService | None = None
        self._snapshot: SchedulerApplicationSnapshot | None = None
        self._config_signature: tuple[int, int] | None = None

        self.reload(reference_time=reference_time)

    @property
    def plan_result(self) -> SchedulerPlanResult:
        if self._plan_result is None:
            raise RuntimeError("scheduler application has not been loaded")
        return self._plan_result

    @property
    def service(self) -> SchedulerService:
        if self._service is None:
            raise RuntimeError("scheduler application has not been loaded")
        return self._service

    @property
    def snapshot(self) -> SchedulerApplicationSnapshot:
        if self._snapshot is None:
            raise RuntimeError("scheduler application has not been loaded")
        return self._snapshot

    def reload(
        self,
        reference_time: datetime | None = None,
    ) -> SchedulerApplicationSnapshot:
        raw_config = self._config_loader(self.config_path)
        if apply_email_env_overrides is not None:
            # Same OEDS_EMAIL_* overrides the admin UI applies; the config file
            # lives in the repo root that also holds crawler/.env.
            raw_config = apply_email_env_overrides(
                dict(raw_config), self.config_path.parent
            )
        crawler_names = known_crawler_names()
        plan_result = build_scheduler_job_plans(raw_config, crawler_names)

        default_config = raw_config.get("default") or {}
        if not isinstance(default_config, Mapping):
            raise ValueError("default config must be a mapping")
        database_uri = default_config.get("database_uri") or default_config.get("db_uri")
        if not database_uri:
            logger.warning(
                "default.database_uri is not set; runs are not protected by the "
                "cross-process crawler lock"
            )
        max_parallel_runs = int(default_config.get("max_parallel_runs", DEFAULT_MAX_PARALLEL_RUNS))
        if max_parallel_runs < 1:
            raise ValueError("default.max_parallel_runs must be at least 1")

        self.dispatcher.runner = CrawlerJobRunner(
            self.config_path,
            post_run_executor=self._post_run_executor,
        )
        self.dispatcher.lock_engine = lock_engine(database_uri) if database_uri else None
        self.dispatcher.max_parallel_runs = max_parallel_runs
        service = SchedulerService(
            plan_result.plans,
            self.dispatcher,
            schedule_factory=self._schedule_factory,
            reference_time=reference_time,
        )

        snapshot = SchedulerApplicationSnapshot(
            config_path=self.config_path,
            crawler_count=len(crawler_names),
            planned_job_count=len(plan_result.plans),
            skipped=plan_result.skipped,
            plan_errors=plan_result.errors,
            service_issues=service.issues,
        )
        self._plan_result = plan_result
        self._service = service
        self._snapshot = snapshot
        self._config_signature = file_signature(self.config_path)
        return snapshot

    def reload_if_changed(
        self,
        reference_time: datetime | None = None,
    ) -> bool:
        current_signature = file_signature(self.config_path)
        if current_signature == self._config_signature:
            return False
        self.reload(reference_time=reference_time)
        return True

    def tick(
        self,
        now: datetime | None = None,
        reload_if_changed: bool = True,
    ) -> tuple[CrawlerRunResult, ...]:
        if reload_if_changed:
            self.reload_if_changed(reference_time=now)
        return self.service.tick(now)


def format_application_summary(snapshot: SchedulerApplicationSnapshot) -> str:
    """Create a compact CLI-friendly application status summary."""

    return "\n".join(
        [
            f"crawlers: {snapshot.crawler_count}",
            f"planned jobs: {snapshot.planned_job_count}",
            f"skipped jobs: {len(snapshot.skipped)}",
            f"plan errors: {len(snapshot.plan_errors)}",
            f"service issues: {len(snapshot.service_issues)}",
        ]
    )
