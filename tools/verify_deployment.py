"""Smoke-check the modular deployment repository without starting services."""

from __future__ import annotations

import argparse
from pathlib import Path


DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = DEPLOYMENT_ROOT.parent
MODULAR_ROOT = MODULES_ROOT.parent
KIT_ROOT = MODULAR_ROOT.parent


def main(local_only: bool = False) -> None:
    _assert_files(
        DEPLOYMENT_ROOT,
        [
            "compose.yml",
            "compose.modular.yml",
            "compose.test.yml",
            "docker/Dockerfile.crawler",
            "docker/Dockerfile.crawler-modular",
            "docker/initdb/09-bootstrap-roles.sh",
            "docker/initdb/10-init.sql",
            "modular_initdb/09-bootstrap-roles.sh",
            "playbooks/oeds-smoke-test.yml",
            "data/provisioning/grafana/README.md",
            "oeds_ops/password_rotation.py",
            "tools/test_db_smoke.ps1",
            "tools/test_real_crawler_smoke.ps1",
            "tools/test_active_crawlers_smoke.ps1",
            "tools/test_stack_smoke.ps1",
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
            ],
        )
        _assert_files(
            MODULAR_ROOT,
            [
                "docs/crawler-inventory.json",
                "sources/oeds-core/oeds/base_crawler.py",
            ],
        )
        _assert_files(
            KIT_ROOT,
            [
                "pyproject.toml",
                "uv.lock",
                ".python-version",
                "crawler/common/base_crawler.py",
                "crawler_core/__init__.py",
                "CRAWLER_CONFIG.yml",
            ],
        )
    _assert_contains(
        DEPLOYMENT_ROOT / "compose.modular.yml",
        [
            "Dockerfile.crawler-modular",
            "oeds-scheduler",
            "oeds-crawler-admin",
            "OEDS_POST_REPO_ROOT",
            "OEDS_ADMIN_REPO_ROOT",
            "${OEDS_RUNTIME_DIR:-../../..}/CRAWLER_CONFIG.yml",
            "required: false",
            "./modular_initdb/09-bootstrap-roles.sh",
            "../oeds-post-scripts/scripts/lib/postgres_functions.sql",
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
            "uv sync --locked",
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
            "down -v --remove-orphans",
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
            "modular stack smoke passed",
            "down -v --remove-orphans",
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
            "active crawler smoke passed",
            "down -v --remove-orphans",
        ],
    )
    _assert_contains(
        DEPLOYMENT_ROOT / "tools" / "test_real_crawler_smoke.ps1",
        [
            "runtime-real-crawler",
            "CrawlerJobRunner",
            "gapfill_smard.py",
            "missing smard.smard table",
            "real crawler smoke passed",
            "down -v --remove-orphans",
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
