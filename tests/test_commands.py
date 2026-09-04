import subprocess
import sys
from pathlib import Path

from oeds_post_scripts.commands import (
    command_to_legacy_argv,
    resolve_post_command,
    script_to_post_command,
)
from oeds_post_scripts.migration import migrate_post_run_scripts


def test_backfill_help_does_not_require_crawler_package():
    script = Path(__file__).resolve().parents[1] / "scripts" / "backfill_entsoe_unavailability.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Backfill ENTSO-E unavailability" in result.stdout


def test_resolve_entsoe_gapfill_command():
    command = resolve_post_command(["gapfill", "entsoe-fms", "--self-test"])

    assert command.spec.legacy_script == "scripts/gapfill_timeseries.py"
    assert command_to_legacy_argv(command) == (
        str(Path("scripts/gapfill_timeseries.py")),
        "--job",
        "entsoe_fms",
        "--self-test",
    )


def test_script_to_post_command_maps_legacy_paths():
    assert script_to_post_command("scripts/gapfill_smard.py") == (
        "oeds-post gapfill smard"
    )
    assert script_to_post_command("scripts/run_price_forecast.py") == (
        "oeds-post forecast day-ahead-price"
    )


def test_migrate_post_run_scripts_replaces_known_legacy_paths():
    migrated, replacements = migrate_post_run_scripts(
        {
            "smard": {
                "post_run_scripts": ["scripts/gapfill_smard.py"],
            },
            "entsoe_fms": {
                "jobs": {
                    "latest": {
                        "post_run_scripts": [
                            "scripts/gapfill_timeseries.py",
                            "scripts/refresh_entsoe_availability_map.py",
                        ]
                    }
                }
            },
        }
    )

    assert migrated["smard"]["post_run_scripts"] == ["oeds-post gapfill smard"]
    assert migrated["entsoe_fms"]["jobs"]["latest"]["post_run_scripts"] == [
        "oeds-post gapfill entsoe-fms",
        "oeds-post refresh entsoe-availability-map",
    ]
    assert [replacement.old_command for replacement in replacements] == [
        "scripts/gapfill_smard.py",
        "scripts/gapfill_timeseries.py",
        "scripts/refresh_entsoe_availability_map.py",
    ]
