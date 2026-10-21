"""Daemon loop wrapper for the modular scheduler application."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from threading import Event

from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.runtime import CrawlerRunResult

logger = logging.getLogger(__name__)


class SchedulerDaemon:
    """Repeatedly tick a scheduler application until stopped."""

    def __init__(
        self,
        application: SchedulerApplication,
        *,
        poll_seconds: float = 60.0,
        busy_poll_seconds: float = 5.0,
        now_func: Callable[[], datetime] = datetime.now,
        sleep_func: Callable[[float], None] = time.sleep,
        stop_event: Event | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.application = application
        self.poll_seconds = poll_seconds
        # While runs are active, tick this often to report finished runs and
        # start jobs that were waiting for a slot or a lock.
        self.busy_poll_seconds = busy_poll_seconds
        self._now_func = now_func
        self._sleep_func = sleep_func
        self._stop_event = stop_event or Event()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop(self) -> None:
        self._stop_event.set()

    def run_once(self, now: datetime | None = None) -> tuple[CrawlerRunResult, ...]:
        results = self.application.tick(now or self._now_func())
        for result in results:
            _log_run_result(result)
        return results

    def seconds_until_next_tick(self, now: datetime | None = None) -> float:
        ref_time = now or self._now_func()
        wait_seconds = self.poll_seconds
        if self.application.service.active_run_count:
            wait_seconds = min(wait_seconds, self.busy_poll_seconds)
        next_run_time = self.application.service.next_run_time
        if next_run_time is not None:
            seconds_until_job = max(0.0, (next_run_time - ref_time).total_seconds())
            wait_seconds = min(wait_seconds, seconds_until_job)
        return wait_seconds

    def run_forever(self) -> None:
        while not self.stopped:
            now = self._now_func()
            try:
                self.run_once(now)
            except Exception:
                # A broken config file (e.g. YAML syntax error on reload) must
                # not kill the daemon; the next successful reload picks up the fix.
                logger.exception(
                    "Scheduler tick failed; retrying in %ss", self.poll_seconds
                )
                wait_seconds = self.poll_seconds
            else:
                wait_seconds = self.seconds_until_next_tick(self._now_func())
            if wait_seconds <= 0:
                continue
            if self._stop_event.wait(wait_seconds):
                break

        # Runs are child processes; let the ones still active finish and
        # report them instead of leaving them unaccounted for.
        for result in self.application.service.wait_for_runs():
            _log_run_result(result)


def _log_run_result(result: CrawlerRunResult) -> None:
    if result.status == "failed":
        logger.error(
            "Scheduled run of %s failed: %s (log: %s)",
            result.display_name,
            _failure_detail(result),
            result.log_path,
        )
    elif result.status == "skipped":
        logger.info("Scheduled run of %s skipped: %s", result.display_name, result.error)
    else:
        logger.info(
            "Scheduled run of %s succeeded in %.1fs (log: %s)",
            result.display_name,
            result.duration_seconds,
            result.log_path,
        )


def _failure_detail(result: CrawlerRunResult) -> str:
    if result.error:
        return result.error
    failed_commands = [
        post_run.command for post_run in result.post_run_results if not post_run.success
    ]
    return "post-run command failed: " + ", ".join(failed_commands)
