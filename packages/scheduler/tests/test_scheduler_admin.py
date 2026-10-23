from __future__ import annotations

import os
import shlex
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import yaml
from crawler.common.crawler_utils import CrawlerSkipped

from crawler_admin.app import (
    _build_gapfill_form_defaults_from_view,
    _build_scheduler_form_state,
    _select_scheduler_job_name,
    _validate_gapfill_form_values,
)
from crawler_admin.config_service import (
    GAPFILL_POSTRUN_SCRIPT,
    CrawlerCard,
    CrawlerJobPreview,
    CronPreview,
    get_repo_root,
    update_crawler_schedule_config_text,
    update_gapfill_config_text,
)
from crawler_admin.gapfill_service import build_gapfill_runtime_view
from crawler_admin.runtime_service import CrawlerRunService, PreparedAction


class SchedulerAdminConfigTest(unittest.TestCase):
    def test_repo_root_prefers_runtime_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "CRAWLER_CONFIG.yml").write_text(
                "default: {}\n",
                encoding="utf-8",
            )
            (temp_path / "crawler").mkdir()
            previous_cwd = Path.cwd()
            try:
                os.chdir(temp_path)
                self.assertEqual(get_repo_root(), temp_path.resolve())
            finally:
                os.chdir(previous_cwd)

    def test_updates_named_scheduler_job_without_touching_crawler_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "CRAWLER_CONFIG.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "default:",
                        "  enable: false",
                        '  schedule: "0 4 * * *"',
                        "entsoe_fms:",
                        "  enable: true",
                        '  schema_name: "entsoe_fms"',
                        "  jobs:",
                        "    latest_hourly:",
                        "      enable: true",
                        '      schedule: "0 * * * *"',
                        "    revision_sweep_daily:",
                        "      enable: false",
                        '      schedule: "30 2 * * *"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            updated_text, created_section = update_crawler_schedule_config_text(
                "entsoe_fms",
                enabled=True,
                schedule="15 3 * * *",
                job_name="revision_sweep_daily",
                repo_root=Path(temp_dir),
            )

        self.assertFalse(created_section)
        updated = yaml.safe_load(updated_text)
        self.assertIs(updated["entsoe_fms"]["enable"], True)
        self.assertEqual(updated["entsoe_fms"]["jobs"]["latest_hourly"]["schedule"], "0 * * * *")
        self.assertIs(updated["entsoe_fms"]["jobs"]["revision_sweep_daily"]["enable"], True)
        self.assertEqual(updated["entsoe_fms"]["jobs"]["revision_sweep_daily"]["schedule"], "15 3 * * *")

    def test_requires_job_selection_for_multi_job_crawler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "CRAWLER_CONFIG.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "default:",
                        '  schedule: "0 4 * * *"',
                        "entsoe_fms:",
                        "  jobs:",
                        "    latest_hourly:",
                        '      schedule: "0 * * * *"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Choose a scheduler job"):
                update_crawler_schedule_config_text(
                    "entsoe_fms",
                    enabled=True,
                    schedule="15 3 * * *",
                    repo_root=Path(temp_dir),
                )

    def test_gapfill_toggle_keeps_exactly_one_post_run_step(self) -> None:
        refresh = "oeds-post refresh entsoe-availability-map"
        settings = {
            "enabled": True,
            "selected_tables": [],
            "target_schema": "entsoe_fms_gapfilled",
            "method": "linear",
            "candidate_periods": ["24h"],
            "donor_context_periods": 6,
            "donor_search_radius": "28d",
            "refinement_periods": 3,
            "max_gap_periods": 24,
            "lookback": "7d",
            "fail_on_table_error": True,
        }
        # (existing post_run_scripts, script_enabled, expected post_run_scripts)
        cases = [
            ([refresh], True, [GAPFILL_POSTRUN_SCRIPT, refresh]),
            ([refresh, "oeds-post gapfill entsoe-fms --tables EnergyPrices"], True,
             [refresh, "oeds-post gapfill entsoe-fms --tables EnergyPrices"]),
            ([refresh, "scripts/gapfill_timeseries.py"], True, [refresh, GAPFILL_POSTRUN_SCRIPT]),
            (["scripts/gapfill_timeseries.py", refresh, GAPFILL_POSTRUN_SCRIPT], True,
             [GAPFILL_POSTRUN_SCRIPT, refresh]),
            ([GAPFILL_POSTRUN_SCRIPT, refresh, "scripts/gapfill_timeseries.py"], False, [refresh]),
        ]
        legacy = {"schema_name": "entsoe_fms", "post_run_scripts": ["scripts/gapfill_timeseries.py"]}
        self.assertTrue(build_gapfill_runtime_view("entsoe_fms", legacy, legacy).script_enabled)

        for scripts, script_enabled, expected in cases:
            with self.subTest(scripts=scripts, script_enabled=script_enabled):
                config = {"schema_name": "entsoe_fms", "post_run_scripts": scripts}
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "CRAWLER_CONFIG.yml"
                    config_path.write_text(
                        yaml.safe_dump({"default": {}, "entsoe_fms": config}), encoding="utf-8"
                    )
                    for _ in range(2):  # saving again changes nothing
                        config_path.write_text(
                            update_gapfill_config_text(
                                "entsoe_fms",
                                script_enabled=script_enabled,
                                repo_root=Path(temp_dir),
                                **settings,
                            ),
                            encoding="utf-8",
                        )
                        saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                        self.assertEqual(saved["entsoe_fms"]["post_run_scripts"], expected)

    def test_gapfill_form_rejects_values_the_gapfill_config_cannot_load(self) -> None:
        config = {"schema_name": "entsoe_fms"}
        overview = SimpleNamespace(crawler_name="entsoe_fms", raw_config=config, effective_config=config)
        values = _build_gapfill_form_defaults_from_view(
            build_gapfill_runtime_view("entsoe_fms", config, config)
        )
        self.assertEqual(_validate_gapfill_form_values(values, overview), [])

        values.update(
            target_schema="",
            max_gap_periods="1.5",
            candidate_periods="24h, often",
            lookback="7days ago",
            table_methods={**values["table_methods"], "EnergyPrices": "magic"},
            selected_tables=["EnergyPrices"],
        )
        errors = _validate_gapfill_form_values(values, overview)

        self.assertEqual(
            errors,
            [
                "Target schema is required.",
                "Max gap periods must be a whole number, not '1.5'.",
                "Candidate periods: 'often' is not a duration such as 24h or 7d.",
                "Lookback: '7days ago' is not a duration such as 24h or 7d.",
                errors[-1],
            ],
        )
        self.assertIn("gapfill method must be one of", errors[-1])

    def test_scheduler_form_uses_selected_job_values(self) -> None:
        card = CrawlerCard(
            name="entsoe_fms",
            description="",
            configured=True,
            module_present=True,
            enabled=True,
            schema_name="entsoe_fms",
            schedule=None,
            schedule_source="jobs",
            preview=CronPreview(schedule=None, summary="2 enabled scheduler job(s)"),
            job_previews=[
                CrawlerJobPreview(
                    name="latest_hourly",
                    enabled=True,
                    schedule="0 * * * *",
                    preview=CronPreview(schedule="0 * * * *", summary="Every hour"),
                ),
                CrawlerJobPreview(
                    name="revision_sweep_daily",
                    enabled=False,
                    schedule="30 2 * * *",
                    preview=CronPreview(schedule="30 2 * * *", summary="Every day at 02:30"),
                ),
            ],
            issues=[],
            state_label="enabled",
            state_variant="ok",
        )
        overview = SimpleNamespace(default_config={"enable": False, "schedule": "0 4 * * *"})

        self.assertEqual(_select_scheduler_job_name(card, None), "latest_hourly")
        form = _build_scheduler_form_state(card, overview, job_name="revision_sweep_daily")

        self.assertEqual(form["enable"], "false")
        self.assertEqual(form["scheduler_mode"], "daily")
        self.assertEqual(form["daily_hour"], "2")
        self.assertEqual(form["daily_minute"], "30")
        self.assertEqual(form["schedule"], "30 2 * * *")


# Stands in for ``oeds-crawl``: parses its arguments and exits with $OEDS_TEST_EXIT_CODE.
CRAWL_STUB = """\
import argparse, os, sys
parser = argparse.ArgumentParser()
parser.add_argument("crawler")
parser.add_argument("--config", required=True)
parser.add_argument("--job")
args = parser.parse_args()
print(f"stub run {args.crawler} config={os.path.basename(args.config)}", flush=True)
code = int(os.environ["OEDS_TEST_EXIT_CODE"])
if code == 1:
    print("RuntimeError: boom", file=sys.stderr)
if code == 3:
    print("Skipped stub: ENTSOE_API_KEY is not configured", file=sys.stderr)
sys.exit(code)
"""


@contextmanager
def _environment(**values: str):
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class CrawlerRunServiceTest(unittest.TestCase):
    def _execute(self, service: CrawlerRunService, executor) -> object:
        prepared = PreparedAction(
            crawler_name="entsoe_fms",
            action_id="run_now",
            action_label="Run once",
            description="Run once.",
            effective_config={},
            config_overrides={},
            action_payload={},
            executor=executor,
        )
        run_id = service._create_run_record(prepared)
        service._execute_run(run_id, prepared)
        return service.get_run(run_id)

    def test_skipped_crawler_run_is_recorded_as_skipped(self) -> None:
        def skip_run(_log: object) -> str | None:
            raise CrawlerSkipped("ENTSOE_API_KEY is not configured")

        with tempfile.TemporaryDirectory() as temp_dir, _environment(OEDS_ADMIN_STATE_DIR=temp_dir):
            record = self._execute(CrawlerRunService(repo_root=Path(temp_dir)), skip_run)

        self.assertEqual(record.status, "skipped")
        self.assertEqual(record.summary, "ENTSOE_API_KEY is not configured")
        self.assertIsNone(record.error_message)

    def test_run_now_maps_oeds_crawl_exit_codes(self) -> None:
        cases = [(0, "succeeded"), (1, "failed"), (3, "skipped")]
        # run_post_scripts: false is honoured like in the scheduler.
        config = {"post_run_scripts": ["oeds-post-not-installed x"], "run_post_scripts": False}
        with tempfile.TemporaryDirectory() as temp_dir:
            stub = Path(temp_dir) / "crawl_stub.py"
            stub.write_text(CRAWL_STUB, encoding="utf-8")
            command = shlex.join([Path(sys.executable).as_posix(), stub.as_posix()])
            for exit_code, expected_status in cases:
                with self.subTest(exit_code=exit_code), _environment(
                    OEDS_ADMIN_STATE_DIR=temp_dir,
                    OEDS_CRAWL_COMMAND=command,
                    OEDS_TEST_EXIT_CODE=str(exit_code),
                ):
                    service = CrawlerRunService(repo_root=Path(temp_dir))
                    plan = service._crawler_plan("entsoe_fms", config)
                    record = self._execute(
                        service,
                        lambda log: service._run_oeds_crawl(plan, log),
                    )
                    log_text = Path(record.log_path).read_text(encoding="utf-8")

                    self.assertEqual(record.status, expected_status)
                    self.assertIn("stub run entsoe_fms config=CRAWLER_CONFIG.yml", log_text)
                    self.assertNotIn("post-run", log_text)
                    if expected_status == "failed":
                        self.assertIn("RuntimeError: boom (exit code 1)", record.error_message)
                    elif expected_status == "skipped":
                        self.assertIn("ENTSOE_API_KEY", record.summary)
                        self.assertIsNone(record.error_message)
                    else:
                        self.assertEqual(record.summary, "Run completed successfully.")


if __name__ == "__main__":
    unittest.main()
