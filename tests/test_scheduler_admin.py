from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from crawler_admin.app import _build_scheduler_form_state, _select_scheduler_job_name
from crawler_admin.config_service import (
    CrawlerCard,
    CrawlerJobPreview,
    CronPreview,
    get_repo_root,
    update_crawler_schedule_config_text,
)
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


class CrawlerRunServiceTest(unittest.TestCase):
    def test_skipped_crawler_run_is_recorded_as_skipped(self) -> None:
        class CrawlerSkipped(Exception):
            """Stands in for crawler.common.crawler_utils.CrawlerSkipped."""

        def skip_run(_crawler: object) -> str | None:
            raise CrawlerSkipped("ENTSOE_API_KEY is not configured")

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_state_dir = os.environ.get("OEDS_ADMIN_STATE_DIR")
            os.environ["OEDS_ADMIN_STATE_DIR"] = temp_dir
            try:
                service = CrawlerRunService(repo_root=Path(temp_dir))
                prepared = PreparedAction(
                    crawler_name="entsoe_fms",
                    action_id="run",
                    action_label="Run once",
                    description="Run once.",
                    effective_config={},
                    config_overrides={},
                    action_payload={},
                    run_post_scripts=False,
                    executor=skip_run,
                    requires_crawler=False,
                )
                run_id = service._create_run_record(prepared, trigger_source="manual")
                service._execute_run(run_id, prepared)
                record = service.get_run(run_id)
            finally:
                if previous_state_dir is None:
                    os.environ.pop("OEDS_ADMIN_STATE_DIR", None)
                else:
                    os.environ["OEDS_ADMIN_STATE_DIR"] = previous_state_dir

        self.assertEqual(record.status, "skipped")
        self.assertEqual(record.summary, "ENTSOE_API_KEY is not configured")
        self.assertIsNone(record.error_message)


if __name__ == "__main__":
    unittest.main()
