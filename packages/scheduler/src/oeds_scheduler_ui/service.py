"""Small scheduler service boundary for planned crawler jobs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from cron_converter import Cron

from oeds_scheduler_ui.planner import SchedulerJobPlan
from oeds_scheduler_ui.runtime import CrawlerRunResult, JobDispatcher


@dataclass(frozen=True)
class SchedulerServiceIssue:
    """Non-fatal service setup issue."""

    job_id: str
    reason: str


class SchedulerService:
    """Enqueue due planned jobs and hand unblocked jobs to the dispatcher."""

    def __init__(
        self,
        plans: Sequence[SchedulerJobPlan],
        dispatcher: JobDispatcher,
        reference_time: datetime | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._jobs: list[tuple[SchedulerJobPlan, Cron]] = []
        self._next_run_times: dict[str, datetime] = {}
        self._issues: list[SchedulerServiceIssue] = []

        self.reload_plans(plans, reference_time=reference_time)

    @property
    def issues(self) -> tuple[SchedulerServiceIssue, ...]:
        return tuple(self._issues)

    @property
    def next_run_time(self) -> datetime | None:
        return min(self._next_run_times.values(), default=None)

    @property
    def active_run_count(self) -> int:
        return self._dispatcher.active_count

    @property
    def pending_job_count(self) -> int:
        return self._dispatcher.pending_count

    def reload_plans(
        self,
        plans: Sequence[SchedulerJobPlan],
        reference_time: datetime | None = None,
    ) -> None:
        ref_time = reference_time or datetime.now()
        self._jobs.clear()
        self._next_run_times.clear()
        self._issues.clear()

        for plan in plans:
            if not plan.schedule:
                self._issues.append(
                    SchedulerServiceIssue(plan.job_id, "job has no schedule")
                )
                continue
            try:
                cron = Cron(plan.schedule)
                next_run_time = cron.schedule(ref_time).next()
            except Exception as exc:
                self._issues.append(
                    SchedulerServiceIssue(
                        plan.job_id,
                        f"invalid schedule {plan.schedule!r}: {exc}",
                    )
                )
                continue

            self._jobs.append((plan, cron))
            self._next_run_times[plan.job_id] = next_run_time

    def enqueue_due_jobs(self, now: datetime | None = None) -> int:
        ref_time = now or datetime.now()
        enqueued = 0
        for plan, cron in self._jobs:
            if self._next_run_times[plan.job_id] <= ref_time:
                if self._dispatcher.queue.enqueue(plan):
                    enqueued += 1
                self._next_run_times[plan.job_id] = cron.schedule(ref_time).next()
        return enqueued

    def dispatch_ready_jobs(self) -> tuple[CrawlerRunResult, ...]:
        return self._dispatcher.dispatch()

    def wait_for_runs(self, timeout: float | None = None) -> tuple[CrawlerRunResult, ...]:
        return self._dispatcher.wait(timeout)

    def tick(self, now: datetime | None = None) -> tuple[CrawlerRunResult, ...]:
        """Enqueue due jobs, start what fits, return runs finished since the last tick."""

        self.enqueue_due_jobs(now)
        return self.dispatch_ready_jobs()
