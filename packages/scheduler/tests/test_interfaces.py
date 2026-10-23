import logging
import shlex
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from oeds_scheduler_ui import application as application_module
from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.daemon import SchedulerDaemon
from oeds_scheduler_ui.locks import CrawlerLock
from oeds_scheduler_ui.planner import (
    build_scheduler_job_plans,
    expand_crawler_job_configs,
    merge_job_config,
)
from oeds_scheduler_ui.runtime import (
    CrawlerJobQueue,
    CrawlerJobRunner,
    CrawlerRunResult,
    JobDispatcher,
    PostRunCommandResult,
    execute_post_command,
)
from oeds_scheduler_ui.service import SchedulerService

DATABASE_URI = "postgresql://user:pass@localhost:5432/opendata"

# Stands in for ``oeds-crawl``: parses the same arguments, echoes them, and
# exits with $OEDS_TEST_EXIT_CODE after sleeping $OEDS_TEST_SLEEP seconds.
CRAWL_STUB = """\
import argparse, os, sys, time
parser = argparse.ArgumentParser()
parser.add_argument("crawler")
parser.add_argument("--config", required=True)
parser.add_argument("--job")
args = parser.parse_args()
print(f"stub run {args.crawler} job={args.job} config={os.path.basename(args.config)}", flush=True)
time.sleep(float(os.environ.get("OEDS_TEST_SLEEP", "0")))
code = int(os.environ.get("OEDS_TEST_EXIT_CODE", "0"))
if code == 1:
    print("RuntimeError: boom", file=sys.stderr)
if code == 3:
    print("Skipped stub: ENTSOE_API_KEY is not configured", file=sys.stderr)
sys.exit(code)
"""


@pytest.fixture
def crawl_stub(tmp_path, monkeypatch):
    """Point OEDS_CRAWL_COMMAND at the stub and run inside ``tmp_path``."""

    stub = tmp_path / "crawl_stub.py"
    stub.write_text(CRAWL_STUB, encoding="utf-8")
    monkeypatch.setenv(
        "OEDS_CRAWL_COMMAND",
        shlex.join([Path(sys.executable).as_posix(), stub.as_posix()]),
    )
    monkeypatch.setenv("OEDS_TEST_EXIT_CODE", "0")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _plan(crawler_name="stub", extra=None, jobs=None, known=("stub",)):
    section = {"schema_name": crawler_name, **(extra or {})}
    if jobs:
        section["jobs"] = jobs
    result = build_scheduler_job_plans(
        {
            "default": {"enable": True, "schedule": "0 4 * * *", "database_uri": DATABASE_URI},
            crawler_name: section,
        },
        known,
    )
    assert not result.errors, result.errors
    return result.plans


def _result(plan, status="succeeded"):
    now = datetime.now()
    return CrawlerRunResult(
        job_id=plan.job_id,
        display_name=plan.display_name,
        crawler_name=plan.crawler_name,
        job_name=plan.job_name,
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        crawler_success=status == "succeeded",
        post_run_success=True,
        success=status == "succeeded",
        status=status,
    )


class FakeRunner:
    """In-process stand-in for CrawlerJobRunner; blocks until ``release`` is set."""

    def __init__(self, block=False):
        self.release = Event()
        self.block = block
        self.started = []

    def run(self, plan):
        self.started.append(plan.job_id)
        if self.block:
            assert self.release.wait(5)
        return _result(plan)


class FakeConnection:
    def __init__(self, lock_free):
        self.lock_free = lock_free
        self.statements = []
        self.closed = False

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))
        return SimpleNamespace(scalar=lambda: self.lock_free)

    def close(self):
        self.closed = True


class FakeEngine:
    def __init__(self, lock_free=True):
        self.lock_free = lock_free
        self.connections = []

    def connect(self):
        connection = FakeConnection(self.lock_free)
        self.connections.append(connection)
        return connection


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        time.sleep(0.01)


# --- planner -----------------------------------------------------------------


def test_planner_expands_named_jobs_with_inherited_config():
    config = {
        "enable": True,
        "schema_name": "entsoe_fms",
        "database_uri": DATABASE_URI,
        "post_run_scripts": ["scripts/gapfill_timeseries.py"],
        "jobs": {
            "latest_hourly": {
                "enable": True,
                "schedule": "0 * * * *",
                "target_data_items": ["ActualTotalLoad_6.1.A_r3"],
            },
            "revision_sweep_daily": {
                "enable": True,
                "schedule": "30 2 * * *",
                "run_post_scripts": False,
            },
        },
    }

    jobs = expand_crawler_job_configs("entsoe_fms", config)

    assert [job.job_id for job in jobs] == [
        "entsoe_fms:latest_hourly",
        "entsoe_fms:revision_sweep_daily",
    ]
    assert jobs[0].config["post_run_scripts"] == ["scripts/gapfill_timeseries.py"]
    assert jobs[0].config["target_data_items"] == ["ActualTotalLoad_6.1.A_r3"]
    assert jobs[1].run_post_scripts is False


def test_planner_builds_plans_for_registered_crawlers_only():
    result = build_scheduler_job_plans(
        {
            "default": {"enable": False, "schedule": "0 4 * * *", "database_uri": DATABASE_URI},
            "smard": {
                "enable": True,
                "schema_name": "smard",
                "post_run_scripts": ["scripts/gapfill_smard.py"],
                "run_timeout_seconds": 3600,
            },
            "missing": {"enable": True, "schema_name": "missing"},
        },
        ["smard", "entsoe_fms"],
    )

    assert not result.errors
    assert [plan.job_id for plan in result.plans] == ["smard:default"]
    assert result.plans[0].post_run_scripts == ("scripts/gapfill_smard.py",)
    assert result.plans[0].run_timeout_seconds == 3600.0
    assert result.skipped[0].crawler_name == "missing"
    assert "entry point" in result.skipped[0].reason


def test_planner_reports_missing_database_uri_and_bad_timeout():
    result = build_scheduler_job_plans(
        {
            "default": {"enable": True, "schedule": "0 4 * * *"},
            "smard": {"schema_name": "smard"},
            "mastr": {"schema_name": "mastr", "database_uri": DATABASE_URI, "run_timeout_seconds": "soon"},
        },
        ["smard", "mastr"],
    )

    assert not result.plans
    assert {(issue.crawler_name, issue.reason) for issue in result.errors} == {
        ("smard", "db_uri or database_uri is required"),
        ("mastr", "run_timeout_seconds must be a positive number: 'soon'"),
    }


def test_merge_job_config_recursively_overrides_nested_values():
    merged = merge_job_config(
        {"email": {"subject": "old", "toaddrs": []}, "enable": False},
        {"email": {"subject": "new"}, "enable": True},
    )

    assert merged == {
        "email": {"subject": "new", "toaddrs": []},
        "enable": True,
    }


# --- runner (oeds-crawl subprocess) ------------------------------------------


@pytest.mark.parametrize(
    "exit_code, status, error_fragment",
    [(0, "succeeded", None), (1, "failed", "RuntimeError: boom (exit code 1)"), (3, "skipped", "ENTSOE_API_KEY")],
)
def test_runner_maps_exit_codes_and_writes_run_log(crawl_stub, monkeypatch, caplog, exit_code, status, error_fragment):
    monkeypatch.setenv("OEDS_TEST_EXIT_CODE", str(exit_code))
    plan = _plan(jobs={"hourly": {"enable": True, "post_run_scripts": ["scripts/after.py"]}})[0]
    post_run_commands = []

    def fake_post_run(command, plan, log):
        post_run_commands.append(command)
        log.write("post-run output\n")
        return PostRunCommandResult(command, 0, True)

    runner = CrawlerJobRunner("CRAWLER_CONFIG.yml", post_run_executor=fake_post_run)
    with caplog.at_level(logging.INFO, logger="stub"):
        result = runner.run(plan)

    assert result.status == status
    assert result.success is (status == "succeeded")
    assert result.job_id == "stub:hourly"
    if error_fragment is None:
        assert result.error is None
    else:
        assert error_fragment in result.error

    log_text = result.log_path.read_text(encoding="utf-8")
    assert result.log_path.parent == crawl_stub / "logs" / "runs"
    assert result.log_path.name.startswith("stub-hourly-")
    assert "stub run stub job=hourly config=CRAWLER_CONFIG.yml" in log_text
    assert log_text.rstrip().endswith(f"# finished: {status}")

    if status == "succeeded":
        assert post_run_commands == ["scripts/after.py"]
        assert "post-run output" in log_text
    else:
        assert post_run_commands == []
    critical = [record for record in caplog.records if record.levelno == logging.CRITICAL]
    if status == "failed":
        assert [record.name for record in critical] == ["stub"]
        assert "boom" in critical[0].getMessage()
        assert str(result.log_path) in critical[0].getMessage()
    else:
        assert critical == []


def test_runner_kills_run_after_timeout(crawl_stub, monkeypatch):
    monkeypatch.setenv("OEDS_TEST_SLEEP", "30")
    plan = _plan(extra={"run_timeout_seconds": 0.5})[0]

    started = time.monotonic()
    result = CrawlerJobRunner("CRAWLER_CONFIG.yml").run(plan)

    assert time.monotonic() - started < 20
    assert result.status == "failed"
    assert "timed out after 0.5s" in result.error


def test_runner_fails_post_run_command_without_critical_log(crawl_stub, caplog):
    plan = _plan(extra={"post_run_scripts": ["scripts/after.py"]})[0]

    def failing_post_run(command, plan, log):
        return PostRunCommandResult(command, 2, False, "exit code 2")

    with caplog.at_level(logging.INFO, logger="stub"):
        result = CrawlerJobRunner("CRAWLER_CONFIG.yml", post_run_executor=failing_post_run).run(plan)

    assert result.status == "failed"
    assert result.crawler_success is True
    assert result.post_run_success is False
    assert result.error is None
    assert all(record.levelno < logging.ERROR for record in caplog.records)


def test_runner_keeps_only_recent_run_logs(crawl_stub):
    runs_dir = crawl_stub / "logs" / "runs"
    runs_dir.mkdir(parents=True)
    for index in range(3):
        old_log = runs_dir / f"old-{index}.log"
        old_log.write_text("old\n", encoding="utf-8")
        stamp = time.time() - 1000 + index
        import os

        os.utime(old_log, (stamp, stamp))

    result = CrawlerJobRunner("CRAWLER_CONFIG.yml", keep_run_logs=2).run(_plan()[0])

    assert sorted(path.name for path in runs_dir.glob("*.log")) == sorted(
        ["old-2.log", result.log_path.name]
    )


def test_execute_post_command_adds_workspace_to_pythonpath_for_legacy_scripts(
    tmp_path,
    monkeypatch,
):
    package = tmp_path / "workspace_pkg"
    package.mkdir()
    (package / "__init__.py").write_text('VALUE = "ok"\n', encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check_import.py").write_text(
        "from workspace_pkg import VALUE\n"
        "print('imported', VALUE)\n"
        "raise SystemExit(0 if VALUE == 'ok' else 1)\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / "run.log"

    with log_path.open("a", encoding="utf-8") as log:
        result = execute_post_command("scripts/check_import.py", plan=None, log=log)

    assert result.success is True
    assert "imported ok" in log_path.read_text(encoding="utf-8")


def test_post_run_command_without_installed_executable_is_skipped_not_failed(crawl_stub, caplog):
    command = "oeds-post-not-installed gapfill stub"
    plan = _plan(extra={"post_run_scripts": [command]})[0]

    with caplog.at_level(logging.INFO):
        result = CrawlerJobRunner("CRAWLER_CONFIG.yml").run(plan)
        SchedulerDaemon(SimpleNamespace(tick=lambda now: (result,))).run_once(datetime.now())

    assert result.status == "succeeded"
    assert result.success is True
    assert result.post_run_results == (PostRunCommandResult(command, None, True, skipped=True),)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert [record.getMessage() for record in warnings] == [
        f"post-processing command not installed; skipped: {command}"
    ]
    assert "succeeded in" in caplog.text
    assert f"post-run skipped (not installed): {command}" in caplog.text
    assert f"# post-run skipped (not installed): {command}" in result.log_path.read_text(encoding="utf-8")


# --- queue, locks, dispatcher ------------------------------------------------


def test_runtime_queue_runs_one_job_per_crawler_and_honours_limit():
    a, b = _plan(jobs={"a": {"enable": True}, "b": {"enable": True}})
    (other,) = _plan("other", known=("other",))
    (third,) = _plan("third", known=("third",))
    queue = CrawlerJobQueue()

    assert queue.enqueue(a) is True
    assert queue.enqueue(a) is False
    for plan in (b, other, third):
        assert queue.enqueue(plan) is True
    assert [plan.job_id for plan in queue.pop_ready_jobs(limit=2)] == ["stub:a", "other:default"]
    assert queue.pending_count == 2
    assert [plan.job_id for plan in queue.pop_ready_jobs()] == ["third:default"]
    queue.mark_finished(a)
    assert [plan.job_id for plan in queue.pop_ready_jobs()] == ["stub:b"]


def test_dispatcher_requeues_job_when_advisory_lock_is_busy(caplog):
    runner = FakeRunner()
    dispatcher = JobDispatcher(runner=runner, lock_engine=FakeEngine(lock_free=False))
    dispatcher.queue.enqueue(_plan()[0])

    with caplog.at_level(logging.INFO, logger="oeds_scheduler_ui.runtime"):
        assert dispatcher.dispatch() == ()

    assert runner.started == []
    assert dispatcher.active_count == 0
    assert dispatcher.pending_count == 1
    assert "already running elsewhere" in caplog.text
    # The next tick tries again and runs once the lock is free.
    dispatcher.lock_engine = FakeEngine(lock_free=True)
    results = [*dispatcher.dispatch(), *dispatcher.wait()]
    assert [result.job_id for result in results] == ["stub:default"]
    assert dispatcher.pending_count == 0


def test_dispatcher_holds_advisory_lock_until_the_run_ends():
    engine = FakeEngine(lock_free=True)
    runner = FakeRunner(block=True)
    dispatcher = JobDispatcher(runner=runner, lock_engine=engine)
    dispatcher.queue.enqueue(_plan()[0])

    dispatcher.dispatch()
    _wait_until(lambda: runner.started == ["stub:default"])
    connection = engine.connections[0]
    assert "pg_try_advisory_lock" in connection.statements[0][0]
    assert connection.statements[0][1] == {"key": "oeds-crawler:stub"}
    assert connection.closed is False

    runner.release.set()
    assert len(dispatcher.wait()) == 1
    assert "pg_advisory_unlock" in connection.statements[1][0]
    assert connection.closed is True


def test_crawler_lock_try_acquire_closes_connection_when_busy():
    engine = FakeEngine(lock_free=False)

    assert CrawlerLock.try_acquire(engine, "smard") is None
    assert engine.connections[0].closed is True


def test_dispatcher_respects_max_parallel_runs():
    runner = FakeRunner(block=True)
    dispatcher = JobDispatcher(runner=runner, max_parallel_runs=2)
    # Distinct crawlers: jobs of one crawler would otherwise run one at a time.
    for name in "abc":
        dispatcher.queue.enqueue(_plan(name, known=(name,))[0])

    assert dispatcher.dispatch() == ()
    _wait_until(lambda: len(runner.started) == 2)
    assert dispatcher.active_count == 2
    assert dispatcher.pending_count == 1
    assert dispatcher.dispatch() == ()  # no free slot yet
    assert len(runner.started) == 2

    runner.release.set()
    finished = dispatcher.wait()
    assert sorted(result.job_id for result in finished) == ["a:default", "b:default"]
    results = [*dispatcher.dispatch(), *dispatcher.wait()]
    assert [result.job_id for result in results] == ["c:default"]
    assert runner.started == ["a:default", "b:default", "c:default"]


# --- service, daemon, application --------------------------------------------

EVERY_MINUTE = "* * * * *"


def test_scheduler_service_enqueues_due_jobs():
    runner = FakeRunner()
    plan = _plan(extra={"schedule": EVERY_MINUTE})[0]
    reference_time = datetime(2026, 1, 1, 0, 0, 0)
    service = SchedulerService(
        [plan],
        JobDispatcher(runner=runner),
        reference_time=reference_time - timedelta(minutes=1),
    )

    assert not service.issues
    assert service.next_run_time == reference_time
    # The run happens in the background; its result is collected by a later
    # tick or by wait_for_runs.
    results = [*service.tick(reference_time), *service.wait_for_runs()]
    assert [result.job_id for result in results] == ["stub:default"]
    assert results[0].success is True
    assert runner.started == ["stub:default"]
    assert service.next_run_time == reference_time + timedelta(minutes=1)
    assert [*service.tick(reference_time), *service.wait_for_runs()] == []


def test_scheduler_service_reports_missing_schedule():
    plan = _plan(extra={"schedule": None})[0]

    service = SchedulerService([plan], JobDispatcher(runner=FakeRunner()))

    assert service.next_run_time is None
    assert service.issues[0].job_id == "stub:default"
    assert service.issues[0].reason == "job has no schedule"


def test_scheduler_daemon_runs_one_tick_and_polls_faster_while_runs_are_active(caplog):
    runner = FakeRunner(block=True)
    plan = _plan(extra={"schedule": EVERY_MINUTE})[0]
    reference_time = datetime(2026, 1, 1, 0, 0, 0)
    service = SchedulerService(
        [plan],
        JobDispatcher(runner=runner),
        reference_time=reference_time - timedelta(minutes=1),
    )

    class App:
        def __init__(self, service):
            self.service = service

        def tick(self, now):
            return self.service.tick(now)

    daemon = SchedulerDaemon(
        App(service),
        poll_seconds=30.0,
        busy_poll_seconds=0.2,
        now_func=lambda: reference_time,
    )

    assert daemon.seconds_until_next_tick(reference_time) == 0.0
    assert daemon.run_once() == ()
    _wait_until(lambda: runner.started == ["stub:default"])
    assert daemon.seconds_until_next_tick(reference_time) == 0.2
    runner.release.set()
    _wait_until(lambda: service.active_run_count == 0)
    assert daemon.seconds_until_next_tick(reference_time) == 30.0  # next run in 60s
    with caplog.at_level(logging.INFO, logger="oeds_scheduler_ui.daemon"):
        assert daemon.run_once(reference_time + timedelta(seconds=30))[0].job_id == "stub:default"
    assert "succeeded" in caplog.text


def test_scheduler_daemon_survives_failing_tick(caplog):
    stop_event = Event()
    ticks = []

    class App:
        service = SimpleNamespace(next_run_time=None, active_run_count=0, wait_for_runs=lambda: ())

        def tick(self, now):
            ticks.append(now)
            if len(ticks) == 1:
                raise ValueError("while parsing a block mapping")
            stop_event.set()
            return ()

    daemon = SchedulerDaemon(
        App(),
        poll_seconds=0.01,
        now_func=lambda: datetime(2026, 1, 1, 0, 0, 0),
        stop_event=stop_event,
    )

    with caplog.at_level(logging.ERROR, logger="oeds_scheduler_ui.daemon"):
        daemon.run_forever()

    assert len(ticks) == 2
    assert "Scheduler tick failed" in caplog.text
    assert "while parsing a block mapping" in caplog.text


def test_application_reloads_changed_config_and_keeps_the_dispatcher(crawl_stub, monkeypatch):
    engines = []

    def fake_lock_engine(database_uri):
        engines.append(database_uri)
        return FakeEngine(lock_free=True)

    monkeypatch.setattr(application_module, "known_crawler_names", lambda: ("stub", "other"))
    monkeypatch.setattr(application_module, "lock_engine", fake_lock_engine)
    config_path = crawl_stub / "CRAWLER_CONFIG.yml"
    config_path.write_text(
        f"default:\n  enable: true\n  schedule: '{EVERY_MINUTE}'\n"
        f"  database_uri: {DATABASE_URI}\n"
        "stub:\n  schema_name: stub\n",
        encoding="utf-8",
    )
    start = datetime(2026, 1, 1, 0, 0, 0)

    app = SchedulerApplication(config_path, reference_time=start)
    dispatcher = app.dispatcher

    assert app.snapshot.ready
    assert app.snapshot.crawler_count == 2
    assert app.snapshot.planned_job_count == 1
    assert dispatcher.max_parallel_runs == 3
    assert engines == [DATABASE_URI]
    assert app.tick(start, reload_if_changed=False) == ()  # nothing due yet

    config_path.write_text(
        f"default:\n  enable: true\n  schedule: '{EVERY_MINUTE}'\n  max_parallel_runs: 1\n"
        f"  database_uri: {DATABASE_URI}\n"
        "stub:\n  schema_name: stub\n"
        "other:\n  schema_name: other\n",
        encoding="utf-8",
    )
    reload_time = start + timedelta(minutes=1)
    assert app.tick(reload_time) == ()  # reloads; schedules restart from here
    assert app.snapshot.planned_job_count == 2
    assert app.dispatcher is dispatcher
    assert dispatcher.max_parallel_runs == 1

    # Both jobs are due; one slot means one run per tick.
    results = [*app.tick(reload_time + timedelta(minutes=1)), *app.service.wait_for_runs()]
    assert app.service.pending_job_count == 1
    results += [*app.tick(reload_time + timedelta(minutes=1.5)), *app.service.wait_for_runs()]
    assert sorted(result.job_id for result in results) == ["other:default", "stub:default"]
    assert all(result.status == "succeeded" for result in results)
    assert len(list((crawl_stub / "logs" / "runs").glob("*.log"))) == 2
