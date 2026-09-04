"""Verify the local modular OEDS scaffolding without external dependencies."""

from __future__ import annotations

import json
import io
import argparse
import os
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_SRC = ROOT / "modules" / "oeds-scheduler-ui" / "src"
CRAWLER_PACK_SRC = ROOT / "modules" / "oeds-crawler-pack" / "src"
POST_SCRIPTS_SRC = ROOT / "modules" / "oeds-post-scripts" / "src"
POST_SCRIPTS_ROOT = ROOT / "modules" / "oeds-post-scripts"
SCHEDULER_UI_ROOT = ROOT / "modules" / "oeds-scheduler-ui"
DEPLOYMENT_ROOT = ROOT / "modules" / "oeds-deployment"


def _add_source_paths() -> None:
    for path in (SCHEDULER_SRC, CRAWLER_PACK_SRC, POST_SCRIPTS_SRC):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)


def _verify_scheduler_interfaces() -> None:
    from oeds_scheduler_ui.interfaces import (
        CrawlerRegistry,
        CrawlerSpec,
        load_crawler_target,
        merge_crawler_registries,
        normalize_crawler_config,
        registry_from_spec_strings,
        run_crawler_instance,
    )
    from oeds_scheduler_ui.distribution import load_inventory, registries_from_inventory
    from oeds_scheduler_ui.discovery import discover_crawler_specs
    from oeds_scheduler_ui.factory import (
        CONSTRUCTOR_CRAWLER_NAME_CONFIG,
        CONSTRUCTOR_SCHEMA_NAME_CONFIG,
        CONSTRUCTOR_SCHEMA_NAME_ONLY,
        CrawlerFactory,
    )
    from oeds_scheduler_ui.planner import build_scheduler_job_plans
    from oeds_scheduler_ui.runtime import (
        CrawlerJobQueue,
        CrawlerJobRunner,
        PostRunCommandResult,
        lock_keys_from_plan,
        run_ready_jobs,
        scheduled_job_from_plan,
    )
    from oeds_scheduler_ui.service import SchedulerService
    from oeds_scheduler_ui.application import (
        SchedulerApplication,
        format_application_summary,
    )
    from oeds_scheduler_ui.daemon import SchedulerDaemon

    config = normalize_crawler_config(
        {
            "schema_name": "smard",
            "database_uri": "postgresql://user:pass@localhost:5432/opendata",
            "schedule": "0 4 * * *",
            "enable": True,
            "region": "DE",
        }
    )
    assert config.schema_name == "smard"
    assert config.options == {"region": "DE"}

    class CoreSmard:
        pass

    class KitSmard:
        pass

    merged = merge_crawler_registries(
        [
            CrawlerRegistry("oeds-crawler-pack", {"smard": KitSmard}),
            CrawlerRegistry("oeds-core", {"smard": CoreSmard}),
        ]
    )
    assert merged["smard"] is KitSmard

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        package = tmp_path / "example_crawlers"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "demo.py").write_text(
            "class DemoCrawler:\n    pass\n",
            encoding="utf-8",
        )
        spec = CrawlerSpec.parse(
            "test-source",
            "example_crawlers.demo:DemoCrawler",
            source_path=tmp_path,
        )
        assert load_crawler_target(spec).__name__ == "DemoCrawler"

        registry = registry_from_spec_strings(
            "oeds-crawler-pack",
            {"smard": "crawler.smard:SmardCrawler"},
            source_path=tmp_path,
        )
        assert registry.crawlers["smard"].source_name == "oeds-crawler-pack"

    class NewCrawler:
        def run(self):
            return "run"

    class LegacyCrawler:
        def crawl_temporal(self):
            return "crawl_temporal"

    assert run_crawler_instance(NewCrawler()) == "run"
    assert run_crawler_instance(LegacyCrawler()) == "crawl_temporal"

    inventory = load_inventory(ROOT / "docs" / "crawler-inventory.json")
    registries = registries_from_inventory(inventory, workspace_root=ROOT)
    merged_inventory = merge_crawler_registries(registries)
    assert merged_inventory["smard"].source_name == "oeds-crawler-pack"
    assert merged_inventory["eurostat_crawler"].source_name == "oeds-crawler-pack"
    assert merged_inventory["chargepoint"].source_name == "oeds-core"
    assert merged_inventory["entsoe_fms"].source_name == "oeds-crawler-pack"
    assert merged_inventory["weather_forecast"].source_name == "oeds-crawler-pack"
    assert merged_inventory["jao_crawler"].source_name == "oeds-core"
    assert len(merged_inventory) >= 45

    kit_discovery = discover_crawler_specs(
        source_name="oeds-crawler-pack",
        source_path=ROOT.parent,
        crawler_package_path="crawler",
        module_prefix="crawler",
    )
    core_discovery = discover_crawler_specs(
        source_name="oeds-core",
        source_path=ROOT / "sources" / "oeds-core",
        crawler_package_path="oeds/crawler",
        module_prefix="oeds.crawler",
    )
    assert len(kit_discovery.crawlers) >= 20
    assert len(core_discovery.crawlers) >= 30

    factory = CrawlerFactory(merged_inventory)
    assert factory.audit("smard").constructor_style == CONSTRUCTOR_CRAWLER_NAME_CONFIG
    assert (
        factory.audit("eurostat_crawler").constructor_style
        == CONSTRUCTOR_CRAWLER_NAME_CONFIG
    )
    assert (
        factory.audit("chargepoint").constructor_style
        == CONSTRUCTOR_SCHEMA_NAME_CONFIG
    )
    assert factory.audit("eex").constructor_style == CONSTRUCTOR_SCHEMA_NAME_ONLY
    assert factory.audit("eex").run_methods == ()

    plan = factory.constructor_plan("smard", config)
    assert plan.constructor_style == CONSTRUCTOR_CRAWLER_NAME_CONFIG
    assert plan.args[0] == "smard"
    assert plan.args[1]["schema_name"] == "smard"

    eex_plan = factory.constructor_plan(
        "eex",
        normalize_crawler_config(
            {
                "schema_name": "eex_prices",
                "database_uri": "postgresql://user:pass@localhost:5432/opendata",
            }
        ),
    )
    assert eex_plan.constructor_style == CONSTRUCTOR_SCHEMA_NAME_ONLY
    assert eex_plan.args == ("eex_prices",)

    unsupported_run_result = build_scheduler_job_plans(
        {
            "default": {
                "enable": True,
                "database_uri": "postgresql://user:pass@localhost:5432/opendata",
            },
            "eex": {
                "enable": True,
                "schema_name": "eex_prices",
            },
        },
        factory,
    )
    assert not unsupported_run_result.plans
    assert unsupported_run_result.errors[0].reason == (
        "crawler has no supported run method"
    )

    scheduler_result = build_scheduler_job_plans(
        {
            "default": {
                "enable": False,
                "schedule": "0 4 * * *",
                "database_uri": "postgresql://user:pass@localhost:5432/opendata",
                "post_run_scripts": None,
            },
            "smard": {
                "enable": True,
                "schema_name": "smard",
                "post_run_scripts": ["scripts/gapfill_smard.py"],
            },
            "entsoe_fms": {
                "enable": True,
                "schema_name": "entsoe_fms",
                "post_run_scripts": [
                    "scripts/gapfill_timeseries.py",
                    "scripts/refresh_entsoe_availability_map.py",
                ],
                "jobs": {
                    "latest_hourly": {
                        "enable": True,
                        "schedule": "0 * * * *",
                        "mode": "fms_package_refresh",
                        "target_data_items": ["ActualTotalLoad_6.1.A_r3"],
                    },
                    "revision_sweep_daily": {
                        "enable": True,
                        "schedule": "30 2 * * *",
                        "mode": "fms_package_refresh",
                        "run_post_scripts": False,
                        "target_data_items": ["EnergyPrices_12.1.D_r3"],
                    },
                },
            },
            "chargepoint": {
                "enable": True,
                "schema_name": "chargepoint",
            },
            "missing_crawler": {
                "enable": True,
                "schema_name": "missing_crawler",
            },
        },
        factory,
    )
    assert not scheduler_result.errors
    assert len(scheduler_result.plans) == 4
    assert any(
        issue.crawler_name == "missing_crawler" for issue in scheduler_result.skipped
    )

    plans_by_id = {plan.job_id: plan for plan in scheduler_result.plans}
    assert plans_by_id["smard:default"].source_name == "oeds-crawler-pack"
    assert plans_by_id["smard:default"].constructor_plan.args[0] == "smard"
    assert plans_by_id["smard:default"].post_run_scripts == (
        "scripts/gapfill_smard.py",
    )
    assert plans_by_id["entsoe_fms:latest_hourly"].schedule == "0 * * * *"
    assert plans_by_id["entsoe_fms:latest_hourly"].run_post_scripts is True
    assert plans_by_id["entsoe_fms:latest_hourly"].raw_config[
        "target_data_items"
    ] == ["ActualTotalLoad_6.1.A_r3"]
    assert (
        plans_by_id["entsoe_fms:revision_sweep_daily"].run_post_scripts is False
    )
    assert plans_by_id["chargepoint:default"].source_name == "oeds-core"

    class RuntimeCrawler:
        constructed: list[tuple[str, dict[str, object]]] = []
        runs: list[str] = []

        def __init__(self, crawler_name, config):
            self.crawler_name = crawler_name
            self.config = config
            RuntimeCrawler.constructed.append((crawler_name, dict(config)))

        def run(self):
            RuntimeCrawler.runs.append(self.crawler_name)
            return {"ran": self.crawler_name}

    runtime_factory = CrawlerFactory(
        merge_crawler_registries(
            [
                CrawlerRegistry(
                    "runtime-test",
                    {"runtime_crawler": RuntimeCrawler},
                )
            ]
        )
    )
    assert (
        runtime_factory.audit("runtime_crawler").constructor_style
        == CONSTRUCTOR_CRAWLER_NAME_CONFIG
    )
    runtime_result = build_scheduler_job_plans(
        {
            "default": {
                "enable": True,
                "schedule": "0 4 * * *",
                "database_uri": "postgresql://user:pass@localhost:5432/opendata",
            },
            "runtime_crawler": {
                "schema_name": "runtime_schema",
                "post_run_scripts": ["scripts/after_runtime.py"],
            },
        },
        runtime_factory,
    )
    assert not runtime_result.errors
    runtime_plan = runtime_result.plans[0]
    post_run_commands: list[str] = []

    def fake_post_run(command, plan):
        post_run_commands.append(f"{plan.job_id}:{command}")
        return PostRunCommandResult(command, 0, True)

    runner = CrawlerJobRunner(runtime_factory, post_run_executor=fake_post_run)
    run_result = runner.run(runtime_plan)
    assert run_result.success is True
    assert run_result.crawler_result == {"ran": "runtime_crawler"}
    assert RuntimeCrawler.constructed[0][0] == "runtime_crawler"
    assert RuntimeCrawler.constructed[0][1]["schema_name"] == "runtime_schema"
    assert RuntimeCrawler.runs == ["runtime_crawler"]
    assert post_run_commands == [
        "runtime_crawler:default:scripts/after_runtime.py"
    ]

    entsoe_lock_keys = lock_keys_from_plan(plans_by_id["entsoe_fms:latest_hourly"])
    assert entsoe_lock_keys == frozenset(
        {"entsoe_fms:ActualTotalLoad_6.1.A_r3"}
    )

    queue = CrawlerJobQueue()
    first_job = scheduled_job_from_plan(runtime_plan, lock_keys=["shared"])
    second_plan = replace(
        runtime_plan,
        job_name="second",
        job_id="runtime_crawler:second",
        display_name="runtime_crawler:second",
    )
    second_job = scheduled_job_from_plan(second_plan, lock_keys=["shared"])
    assert queue.enqueue(first_job) is True
    assert queue.enqueue(first_job) is False
    assert queue.enqueue(second_job) is True
    first_ready = queue.pop_ready_jobs()
    assert len(first_ready) == 1
    assert first_ready[0].job.job_id == "runtime_crawler:default"
    second_ready_blocked = queue.pop_ready_jobs()
    assert second_ready_blocked == ()
    queue.mark_finished(first_job)
    second_ready = queue.pop_ready_jobs()
    assert len(second_ready) == 1
    assert second_ready[0].job.job_id == "runtime_crawler:second"
    queue.mark_finished(second_job)

    RuntimeCrawler.runs.clear()
    queue.enqueue(first_job)
    ready_results = run_ready_jobs(queue, runner)
    assert len(ready_results) == 1
    assert ready_results[0].success is True
    assert RuntimeCrawler.runs == ["runtime_crawler"]

    class EverySecondSchedule:
        def next_after(self, ref_time):
            return ref_time + timedelta(seconds=1)

    RuntimeCrawler.runs.clear()
    service_reference_time = datetime(2026, 1, 1, 0, 0, 0)
    service = SchedulerService(
        [runtime_plan],
        runner,
        schedule_factory=lambda expression: EverySecondSchedule(),
        reference_time=service_reference_time - timedelta(seconds=1),
    )
    assert not service.issues
    assert service.next_run_time == service_reference_time
    service_results = service.tick(service_reference_time)
    assert len(service_results) == 1
    assert service_results[0].success is True
    assert RuntimeCrawler.runs == ["runtime_crawler"]
    assert service.next_run_time == service_reference_time + timedelta(seconds=1)
    assert service.tick(service_reference_time) == ()

    with tempfile.TemporaryDirectory() as tmp:
        app_root = Path(tmp)
        crawler_package = app_root / "crawler"
        crawler_package.mkdir()
        (crawler_package / "__init__.py").write_text("", encoding="utf-8")
        (crawler_package / "demo.py").write_text(
            "class DemoCrawler:\n"
            "    def __init__(self, crawler_name, config):\n"
            "        self.crawler_name = crawler_name\n"
            "        self.config = config\n"
            "    def run(self):\n"
            "        return self.config['schema_name']\n",
            encoding="utf-8",
        )
        inventory_path = app_root / "crawler-inventory.json"
        inventory_path.write_text(
            json.dumps(
                {
                    "registry_priority": ["runtime-test"],
                    "pilot": {
                        "demo": {
                            "preferred_source": "runtime-test",
                            "source_path": ".",
                            "module": "crawler.demo",
                            "attribute": "DemoCrawler",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        config_path = app_root / "CRAWLER_CONFIG.yml"
        config_path.write_text("initial config placeholder\n", encoding="utf-8")
        app_config_holder = {
            "data": {
                "default": {
                    "enable": True,
                    "schedule": "1",
                    "database_uri": "postgresql://user:pass@localhost:5432/opendata",
                },
                "demo": {
                    "schema_name": "demo_schema",
                },
            }
        }

        app = SchedulerApplication(
            config_path=config_path,
            inventory_path=inventory_path,
            workspace_root=app_root,
            schedule_factory=lambda expression: EverySecondSchedule(),
            config_loader=lambda path: app_config_holder["data"],
            reference_time=service_reference_time - timedelta(seconds=1),
        )
        assert app.snapshot.ready is True
        assert app.snapshot.crawler_count == 1
        assert app.snapshot.planned_job_count == 1
        assert "planned jobs: 1" in format_application_summary(app.snapshot)
        daemon = SchedulerDaemon(
            app,
            poll_seconds=30.0,
            now_func=lambda: service_reference_time,
        )
        assert daemon.seconds_until_next_tick(service_reference_time) == 0.0
        app_results = daemon.run_once()
        assert len(app_results) == 1
        assert app_results[0].crawler_result == "demo_schema"
        assert daemon.seconds_until_next_tick(service_reference_time) == 1.0

        app_config_holder["data"] = {
            "default": {
                "enable": True,
                "schedule": "1",
                "database_uri": "postgresql://user:pass@localhost:5432/opendata",
            },
            "demo": {
                "enable": False,
                "schema_name": "demo_schema",
            },
        }
        config_path.write_text(
            "changed config placeholder with disabled demo\n",
            encoding="utf-8",
        )
        assert app.reload_if_changed(reference_time=service_reference_time) is True
        assert app.snapshot.planned_job_count == 0
        assert app.snapshot.skipped[0].reason == "job is disabled"


def _verify_crawler_pack() -> None:
    from oeds_crawler_pack.registry import default_kit_source_path, get_crawler_specs

    specs = get_crawler_specs()
    assert specs["smard"] == "crawler.smard:SmardCrawler"
    assert specs["eurostat_crawler"] == "crawler.eurostat_crawler:EurostatCrawler"
    assert specs["entsoe_fms"] == "crawler.entsoe_fms:EntsoeFMSCrawler"
    assert specs["weather_forecast"] == "crawler.weather_forecast:WeatherForecastCrawler"
    assert len(specs) >= 20
    assert (default_kit_source_path() / "crawler").is_dir()


def _verify_post_scripts() -> None:
    from oeds_post_scripts.commands import (
        command_to_legacy_argv,
        list_post_commands,
        resolve_post_command,
        script_to_post_command,
    )
    from oeds_post_scripts.cli import main as post_cli_main
    from oeds_post_scripts.migration import migrate_post_run_scripts
    from oeds_post_scripts.runner import resolve_post_repo_root

    commands = {spec.scheduler_command: spec for spec in list_post_commands()}
    assert "oeds-post gapfill smard" in commands
    assert "oeds-post gapfill entsoe-fms" in commands
    assert "oeds-post refresh entsoe-availability-map" in commands
    assert "oeds-post forecast day-ahead-price" in commands

    entsoe_gapfill = resolve_post_command(
        ["gapfill", "entsoe-fms", "--self-test"]
    )
    entsoe_argv = command_to_legacy_argv(
        entsoe_gapfill,
        repo_root=ROOT.parent,
    )
    assert Path(entsoe_argv[0]).name == "gapfill_timeseries.py"
    assert entsoe_argv[1:] == ("--job", "entsoe_fms", "--self-test")

    assert script_to_post_command("scripts/gapfill_smard.py") == (
        "oeds-post gapfill smard"
    )
    assert script_to_post_command("scripts/gapfill_timeseries.py") == (
        "oeds-post gapfill entsoe-fms"
    )
    assert script_to_post_command("scripts/refresh_entsoe_availability_map.py") == (
        "oeds-post refresh entsoe-availability-map"
    )
    assert script_to_post_command("scripts/run_price_forecast.py") == (
        "oeds-post forecast day-ahead-price"
    )

    old_env_root = os.environ.get("OEDS_POST_REPO_ROOT")
    os.environ["OEDS_POST_REPO_ROOT"] = str(POST_SCRIPTS_ROOT)
    try:
        assert resolve_post_repo_root(None) == POST_SCRIPTS_ROOT.resolve()
    finally:
        if old_env_root is None:
            os.environ.pop("OEDS_POST_REPO_ROOT", None)
        else:
            os.environ["OEDS_POST_REPO_ROOT"] = old_env_root

    migrated_config, replacements = migrate_post_run_scripts(
        {
            "smard": {
                "post_run_scripts": ["scripts/gapfill_smard.py"],
            },
            "entsoe_fms": {
                "jobs": {
                    "latest_hourly": {
                        "post_run_scripts": [
                            "scripts/gapfill_timeseries.py",
                            "scripts/refresh_entsoe_availability_map.py",
                        ]
                    }
                }
            },
        }
    )
    assert migrated_config["smard"]["post_run_scripts"] == [
        "oeds-post gapfill smard"
    ]
    assert migrated_config["entsoe_fms"]["jobs"]["latest_hourly"][
        "post_run_scripts"
    ] == [
        "oeds-post gapfill entsoe-fms",
        "oeds-post refresh entsoe-availability-map",
    ]
    assert len(replacements) == 3

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "CRAWLER_CONFIG.yml"
        output_path = tmp_path / "CRAWLER_CONFIG.post.yml"
        config_path.write_text(
            "default:\n"
            "  enable: false\n"
            "smard:\n"
            "  post_run_scripts:\n"
            "    - scripts/gapfill_smard.py\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            post_cli_main(
                [
                    "--migrate-config",
                    str(config_path),
                    "--output",
                    str(output_path),
                    "--json",
                ]
            )
        assert "oeds-post gapfill smard" in output_path.read_text(encoding="utf-8")
        assert "scripts/gapfill_smard.py" in stdout.getvalue()

        try:
            with redirect_stdout(io.StringIO()):
                post_cli_main(["--migrate-config", str(config_path), "--check"])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("--check should fail when replacements are found")


def _verify_inventory() -> None:
    inventory_path = ROOT / "docs" / "crawler-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["pilot"]["smard"]["preferred_source"] == "oeds-crawler-pack"
    assert inventory["pilot"]["chargepoint"]["preferred_source"] == "oeds-core"


def _verify_split_artifacts(skip_split_parity: bool = False) -> None:
    from verify_split_parity import verify_split_parity

    split_files = [
        "README.md",
        ".gitignore",
        "docs/intern-test-vm-test-plan.md",
        "docs/publication-readiness.md",
        "docs/release-prep-2026-06-05.md",
        "docs/full-function-test-2026-06-02.md",
        "tools/check_publication_readiness.py",
        "tools/run_full_function_test.ps1",
    ]
    for relative_path in split_files:
        assert (ROOT / relative_path).is_file(), relative_path

    module_roots = [
        ROOT / "modules" / "oeds-crawler-pack",
        SCHEDULER_UI_ROOT,
        POST_SCRIPTS_ROOT,
        DEPLOYMENT_ROOT,
    ]
    for module_root in module_roots:
        license_path = module_root / "LICENSES" / "AGPL-3.0-or-later.txt"
        assert license_path.is_file(), str(license_path.relative_to(ROOT))
        workflow_path = module_root / ".github" / "workflows" / "ci.yml"
        assert workflow_path.is_file(), str(workflow_path.relative_to(ROOT))

    post_script_files = [
        "scripts/gapfill_smard.py",
        "scripts/gapfill_timeseries.py",
        "scripts/refresh_entsoe_availability_map.py",
        "scripts/run_price_forecast.py",
        "scripts/backfill_entsoe_unavailability.py",
        "scripts/lib/gapfill.py",
        "scripts/lib/gapfiller/db.py",
        "scripts/lib/entsoe_availability_map.sql",
        "oeds_gapfill/config.py",
        "oeds_gapfill/core.py",
        "oeds_price_forecast/model.py",
        "oeds_price_forecast/upstream.py",
    ]
    for relative_path in post_script_files:
        assert (POST_SCRIPTS_ROOT / relative_path).is_file(), relative_path

    deployment_files = [
        "compose.yml",
        "compose.modular.yml",
        "docker/Dockerfile.crawler",
        "docker/Dockerfile.crawler-modular",
        "docker/initdb/10-init.sql",
        "modular_initdb/09-bootstrap-roles.sh",
        "playbooks/oeds-smoke-test.yml",
        "playbooks/oeds-docker-config.yml",
        "playbooks/tasks/oeds-repo-deploy.yml",
        "oeds_ops/password_rotation.py",
        "data/provisioning/grafana/README.md",
        "tools/verify_deployment.py",
        "tools/test_db_smoke.ps1",
        "tools/test_db_smoke.sh",
        "tools/test_real_crawler_smoke.ps1",
        "tools/test_real_crawler_smoke.sh",
        "tools/test_active_crawlers_smoke.ps1",
        "tools/test_active_crawlers_smoke.sh",
        "tools/test_stack_smoke.ps1",
        "tools/test_stack_smoke.sh",
        "tools/smoke_lib.sh",
    ]
    for relative_path in deployment_files:
        assert (DEPLOYMENT_ROOT / relative_path).is_file(), relative_path

    admin_files = [
        "src/crawler_admin/app.py",
        "src/crawler_admin/config_service.py",
        "src/crawler_admin/runtime_service.py",
        "src/crawler_admin/templates/dashboard.html",
        "src/crawler_admin/static/admin.css",
        "src/crawler_admin_server.py",
    ]
    for relative_path in admin_files:
        assert (SCHEDULER_UI_ROOT / relative_path).is_file(), relative_path

    compatibility_manifest = (
        DEPLOYMENT_ROOT / "compatibility.yml"
    ).read_text(encoding="utf-8")
    assert "oeds-post gapfill entsoe-fms" in compatibility_manifest
    assert "oeds-post --migrate-config CRAWLER_CONFIG.yml --check" in (
        compatibility_manifest
    )
    assert "github-initial" in compatibility_manifest
    assert (
        "https://github.com/johannesschuhmacher/oeds-scheduler-ui.git"
        in compatibility_manifest
    )
    assert "publication-readiness.md" in compatibility_manifest
    assert "test_active_crawlers_smoke.ps1 -IncludeEntsoeFms" in compatibility_manifest

    migrated_config = ROOT / "generated" / "CRAWLER_CONFIG.post.yml"
    assert migrated_config.is_file()
    migrated_config_text = migrated_config.read_text(encoding="utf-8")
    assert "oeds-post gapfill smard" in migrated_config_text
    assert "oeds-post gapfill entsoe-fms" in migrated_config_text
    assert "oeds-post refresh entsoe-availability-map" in migrated_config_text
    assert "oeds-post forecast day-ahead-price" in migrated_config_text
    if not skip_split_parity:
        assert sum(check.file_count for check in verify_split_parity()) > 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-split-parity",
        action="store_true",
        help=(
            "skip byte-for-byte parity against the KIT source checkout; use this "
            "for assembled compatibility workspaces where module pins can be newer "
            "than the pinned KIT source"
        ),
    )
    return parser.parse_args()


def main(skip_split_parity: bool = False) -> None:
    _add_source_paths()
    _verify_scheduler_interfaces()
    _verify_crawler_pack()
    _verify_post_scripts()
    _verify_inventory()
    _verify_split_artifacts(skip_split_parity=skip_split_parity)
    print("modular repository scaffold verification passed")


if __name__ == "__main__":
    args = _parse_args()
    main(skip_split_parity=args.skip_split_parity)
