"""Smoke-check the modular deployment repository without starting services."""

from __future__ import annotations

import argparse
from pathlib import Path


DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = DEPLOYMENT_ROOT.parent
MODULAR_ROOT = MODULES_ROOT.parent


def main(local_only: bool = False) -> None:
    _assert_files(
        DEPLOYMENT_ROOT,
        [
            "compose.yml",
            "compose.modular.yml",
            "compose.test.yml",
            "docker/Dockerfile.crawler-modular",
            "docker/initdb/09-bootstrap-roles.sh",
            "docker/initdb/10-init.sql",
            "modular_initdb/09-bootstrap-roles.sh",
            "playbooks/oeds-smoke-test.yml",
            "data/provisioning/grafana/README.md",
            "assembly/crawler-inventory.json",
            "assembly/modular_repos/README.md",
            "assembly/modular_repos/docs/publication-readiness.md",
            "assembly/modular_repos/generated/CRAWLER_CONFIG.post.yml",
            "assembly/modular_repos/tools/verify_modules.py",
            "oeds_ops/password_rotation.py",
            "tools/assemble_workspace.py",
            "tools/test_db_smoke.ps1",
            "tools/test_db_smoke.sh",
            "tools/test_real_crawler_smoke.ps1",
            "tools/test_real_crawler_smoke.sh",
            "tools/test_active_crawlers_smoke.ps1",
            "tools/test_active_crawlers_smoke.sh",
            "tools/test_stack_smoke.ps1",
            "tools/test_stack_smoke.sh",
            "tools/smoke_lib.sh",
            "tools/oeds_clean_install_from_git.sh",
            "tools/load_sample_data.sh",
        ],
    )
    if not local_only:
        _assert_files(
            MODULES_ROOT / "oeds-scheduler-ui",
            [
                "pyproject.toml",
                "src/oeds_scheduler_ui/cli.py",
                "src/crawler_admin/app.py",
                "src/crawler_admin_server.py",
            ],
        )
        _assert_files(
            MODULES_ROOT / "oeds-post-scripts",
            [
                "pyproject.toml",
                "src/oeds_post_scripts/cli.py",
                "scripts/lib/postgres_functions.sql",
                "oeds_gapfill/core.py",
                "oeds_price_forecast/model.py",
            ],
        )
        _assert_files(
            MODULES_ROOT / "oeds-crawler-pack",
            [
                "pyproject.toml",
                "src/oeds_crawler_pack/registry.py",
                "src/crawler/common/base_crawler.py",
                "src/crawler_core/__init__.py",
                "src/crawler/smard.py",
            ],
        )
        _assert_files(
            MODULAR_ROOT,
            [
                "docs/crawler-inventory.json",
                "sources/oeds-core/oeds/base_crawler.py",
            ],
        )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "assemble_workspace.py",
        [
            "compatibility.yml",
            "oeds-crawler-pack",
            "CRAWLER_CONFIG.yml",
            "crawler/data",
            "crawler-inventory.json",
            "modular_repos",
            "verify_modules.py",
            "assembled modular OEDS workspace",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "assembly" / "crawler-inventory.json",
        [
            "oeds-crawler-pack",
            "oeds-core",
            "registry_priority",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "compatibility.yml",
        [
            "self: true",
            "oeds-scheduler-ui.git",
            "oeds-post-scripts.git",
            "oeds-crawler-pack.git",
        ],
    )
    _assert_not_contains(
        DEPLOYMENT_ROOT / "compatibility.yml",
        ["oeds-kit-source", "open-energy-data-server-KIT"],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "compose.modular.yml",
        [
            "Dockerfile.crawler-modular",
            "oeds-scheduler",
            "oeds-crawler-admin",
            "OEDS_ADMIN_REPO_ROOT",
            "${OEDS_RUNTIME_DIR:-../../..}/CRAWLER_CONFIG.yml",
            "required: false",
            "./modular_initdb/09-bootstrap-roles.sh",
            "../oeds-post-scripts/scripts/lib/postgres_functions.sql",
        ],
    )
    for playbook_name in (
        "oeds-docker-config.yml",
        "oeds-update.yml",
        "oeds-uninstall.yml",
    ):
        _assert_contains(
            DEPLOYMENT_ROOT / "playbooks" / playbook_name,
            [
                "oeds_compose_dir_effective",
                "oeds_compose_files_effective",
                "{% for compose_file in oeds_compose_files_effective %}",
            ],
        )
    _assert_contains(
        DEPLOYMENT_ROOT / "compose.test.yml",
        [
            "oeds-modular-test",
            "oeds-modular-test-open-data",
            "oeds-modular-test-postgres-home",
            "!override",
            "OEDS_TEST_POSTGRES_PORT",
            "13010",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "docker" / "Dockerfile.crawler-modular",
        [
            "uv venv",
            "uv pip install",
            "PYTHONPATH=/app",
            "oeds-crawler-pack",
            "oeds-scheduler-ui",
            "oeds-post-scripts",
            "modular_repos/sources/oeds-core",
            "oeds-scheduler",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_db_smoke.ps1",
        [
            "compose.test.yml",
            "missing readonly role",
            "missing postgis extension",
            "missing public.linear_interpolate",
            "COMPOSE_PROJECT_NAME",
            "down -v --remove-orphans",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_db_smoke.sh",
        [
            "compose.test.yml",
            "missing readonly role",
            "missing postgis extension",
            "missing public.linear_interpolate",
            "COMPOSE_PROJECT_NAME",
            "isolated DB smoke passed",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_stack_smoke.ps1",
        [
            "runtime-stack",
            "open-postgrest",
            "grafana",
            "crawler-admin",
            "--profile",
            "13001",
            "13006",
            "13010",
            "COMPOSE_PROJECT_NAME",
            "modular stack smoke passed",
            "down -v --remove-orphans",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_stack_smoke.sh",
        [
            "runtime-stack",
            "open-postgrest",
            "grafana",
            "crawler-admin",
            "13001",
            "13006",
            "13010",
            "COMPOSE_PROJECT_NAME",
            "modular stack smoke passed",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_active_crawlers_smoke.ps1",
        [
            "runtime-active-crawlers",
            "entsoe_api",
            "power_system_data",
            "weather_forecast",
            "IncludeEntsoeFms",
            "COMPOSE_PROJECT_NAME",
            "active crawler smoke passed",
            "down -v --remove-orphans",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_active_crawlers_smoke.sh",
        [
            "runtime-active-crawlers",
            "entsoe_api",
            "power_system_data",
            "weather_forecast",
            "--include-entsoe-fms",
            "COMPOSE_PROJECT_NAME",
            "active crawler smoke passed",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_real_crawler_smoke.ps1",
        [
            "runtime-real-crawler",
            "CrawlerJobRunner",
            "oeds-post gapfill smard",
            "missing smard.smard table",
            "COMPOSE_PROJECT_NAME",
            "real crawler smoke passed",
            "down -v --remove-orphans",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_real_crawler_smoke.sh",
        [
            "runtime-real-crawler",
            "CrawlerJobRunner",
            "oeds-post gapfill smard",
            "missing smard.smard table",
            "COMPOSE_PROJECT_NAME",
            "real crawler smoke passed",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "oeds_clean_install_from_git.sh",
        [
            "OEDS_GIT_TOKEN",
            "GIT_ASKPASS",
            "OEDS_CRAWLER_ENV_FILE",
            "--crawler-env-file",
            "assemble_workspace.py",
            "oeds_repo_source_mode=local_worktree",
            "oeds_compose_dir=",
            "oeds-smoke-test.yml",
            "load_sample_data.sh",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "load_sample_data.sh",
        [
            "runtime-load-sample-data",
            "smard",
            "entsoe_api",
            "power_system_data",
            "weather_forecast",
            "--include-entsoe-fms",
            "oeds-crawler-pack/src/crawler/data",
            "oeds-post gapfill smard",
            "sample data load passed",
        ],
    )
    if local_only:
        print("deployment repository verification passed")
    else:
        print("deployment module verification passed")


def _assert_files(root: Path, relative_paths: list[str]) -> None:
    assert root.is_dir(), f"missing directory: {root}"
    for relative_path in relative_paths:
        path = root / relative_path
        assert path.is_file(), f"missing file: {path}"


def _assert_contains(path: Path, expected_tokens: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in expected_tokens:
        assert token in text, f"{path} does not contain {token!r}"


def _assert_not_contains(path: Path, rejected_tokens: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in rejected_tokens:
        assert token not in text, f"{path} unexpectedly contains {token!r}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="check only files that are expected inside the deployment repo",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(local_only=args.local_only)
