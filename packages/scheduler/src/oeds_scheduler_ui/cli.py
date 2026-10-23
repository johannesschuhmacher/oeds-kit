"""Command line entry point for the scheduler add-on."""

from __future__ import annotations

import argparse
import logging
import signal
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Sequence

from oeds_scheduler_ui.application import (
    SchedulerApplication,
    format_application_summary,
)
from oeds_scheduler_ui.daemon import SchedulerDaemon


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="oeds-scheduler")
    parser.add_argument(
        "--config",
        default="CRAWLER_CONFIG.yml",
        help="scheduler YAML config path",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one scheduler tick after loading and wait for the started runs",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="run a persistent scheduler loop",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=60.0,
        help="maximum seconds between config checks",
    )
    args = parser.parse_args(argv)

    app = SchedulerApplication(
        config_path=Path(args.config),
        reference_time=datetime.now(),
    )
    print(format_application_summary(app.snapshot))

    if args.once:
        results = list(app.tick(datetime.now(), reload_if_changed=False))
        while True:
            results.extend(app.service.wait_for_runs())
            if not app.service.pending_job_count:
                break
            results.extend(app.service.dispatch_ready_jobs())
            if not app.service.active_run_count:
                break  # the rest cannot start now (crawler running elsewhere)
        for result in results:
            detail = f" ({result.error})" if result.error else ""
            print(f"{result.display_name}: {result.status}{detail}")
        print(f"ran jobs: {len(results)}")
        return

    if args.daemon:
        stop_event = Event()

        def stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, stop)

        daemon = SchedulerDaemon(
            app,
            poll_seconds=args.poll_seconds,
            stop_event=stop_event,
        )
        daemon.run_forever()


if __name__ == "__main__":
    main()
