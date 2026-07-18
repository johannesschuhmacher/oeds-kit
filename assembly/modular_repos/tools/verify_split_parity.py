"""Verify that mechanically split modules still match the current KIT source."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT_ROOT = ROOT.parent
POST_SCRIPTS_ROOT = ROOT / "modules" / "oeds-post-scripts"
DEPLOYMENT_ROOT = ROOT / "modules" / "oeds-deployment"
SCHEDULER_UI_ROOT = ROOT / "modules" / "oeds-scheduler-ui"

EXCLUDED_NAMES = {"__pycache__", ".git"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_RELATIVE_FILES = {
    Path("Dockerfile.crawler-modular"),
    Path("oeds-docker-config.yml"),
    Path("oeds-uninstall.yml"),
    Path("oeds-update.yml"),
}


@dataclass(frozen=True)
class ParityCheck:
    name: str
    source: Path
    target: Path
    file_count: int


def verify_split_parity() -> tuple[ParityCheck, ...]:
    """Raise ``AssertionError`` if copied split artifacts drift from KIT."""

    checks = (
        ("post:oeds_gapfill", KIT_ROOT / "oeds_gapfill", POST_SCRIPTS_ROOT / "oeds_gapfill"),
        (
            "post:oeds_price_forecast",
            KIT_ROOT / "oeds_price_forecast",
            POST_SCRIPTS_ROOT / "oeds_price_forecast",
        ),
        ("post:scripts-lib", KIT_ROOT / "scripts" / "lib", POST_SCRIPTS_ROOT / "scripts" / "lib"),
        ("deploy:docker", KIT_ROOT / "docker", DEPLOYMENT_ROOT / "docker"),
        ("deploy:playbooks", KIT_ROOT / "playbooks", DEPLOYMENT_ROOT / "playbooks"),
        (
            "deploy:grafana-provisioning",
            KIT_ROOT / "data" / "provisioning",
            DEPLOYMENT_ROOT / "data" / "provisioning",
        ),
        ("deploy:oeds_ops", KIT_ROOT / "oeds_ops", DEPLOYMENT_ROOT / "oeds_ops"),
        (
            "scheduler-ui:crawler-admin",
            KIT_ROOT / "crawler_admin",
            SCHEDULER_UI_ROOT / "src" / "crawler_admin",
        ),
    )

    results = [_verify_tree(name, source, target) for name, source, target in checks]

    script_files = [
        "backfill_entsoe_unavailability.py",
        "gapfill_smard.py",
        "gapfill_timeseries.py",
        "generate_additional_energy_dashboards.py",
        "generate_entsoe_hydro_dashboards.py",
        "generate_entsoe_negative_price_dashboards.py",
        "generate_glohydrores_dashboard.py",
        "import_glohydrores.py",
        "refresh_entsoe_availability_map.py",
        "run_price_forecast.py",
    ]
    for script_file in script_files:
        _assert_same_file(
            KIT_ROOT / "scripts" / script_file,
            POST_SCRIPTS_ROOT / "scripts" / script_file,
        )
    results.append(
        ParityCheck(
            name="post:script-entrypoints",
            source=KIT_ROOT / "scripts",
            target=POST_SCRIPTS_ROOT / "scripts",
            file_count=len(script_files),
        )
    )

    _assert_same_file(KIT_ROOT / "compose.yml", DEPLOYMENT_ROOT / "compose.yml")
    results.append(
        ParityCheck(
            name="deploy:compose",
            source=KIT_ROOT / "compose.yml",
            target=DEPLOYMENT_ROOT / "compose.yml",
            file_count=1,
        )
    )

    _assert_same_file(
        KIT_ROOT / "crawler_admin_server.py",
        SCHEDULER_UI_ROOT / "src" / "crawler_admin_server.py",
    )
    results.append(
        ParityCheck(
            name="scheduler-ui:crawler-admin-server",
            source=KIT_ROOT / "crawler_admin_server.py",
            target=SCHEDULER_UI_ROOT / "src" / "crawler_admin_server.py",
            file_count=1,
        )
    )

    return tuple(results)


def _verify_tree(name: str, source: Path, target: Path) -> ParityCheck:
    assert source.is_dir(), f"missing source directory: {source}"
    assert target.is_dir(), f"missing target directory: {target}"

    source_files = _relative_files(source)
    target_files = _relative_files(target)
    assert source_files == target_files, (
        f"{name} file set differs: "
        f"missing={sorted(source_files - target_files)} "
        f"extra={sorted(target_files - source_files)}"
    )

    for relative_path in sorted(source_files):
        _assert_same_file(source / relative_path, target / relative_path)

    return ParityCheck(name=name, source=source, target=target, file_count=len(source_files))


def _relative_files(root: Path) -> set[Path]:
    files: set[Path] = set()
    for path in root.rglob("*"):
        if any(part in EXCLUDED_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        if path.is_file():
            relative_path = path.relative_to(root)
            if relative_path in EXCLUDED_RELATIVE_FILES:
                continue
            files.add(relative_path)
    return files


def _assert_same_file(source: Path, target: Path) -> None:
    assert source.is_file(), f"missing source file: {source}"
    assert target.is_file(), f"missing target file: {target}"
    assert _sha256(source) == _sha256(target), f"file content differs: {source} -> {target}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    checks = verify_split_parity()
    for check in checks:
        print(f"{check.name}: {check.file_count} files match")
    print("split parity verification passed")


if __name__ == "__main__":
    main()
