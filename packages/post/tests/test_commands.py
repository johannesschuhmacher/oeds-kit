import os
import subprocess
import sys
from types import ModuleType
from pathlib import Path

import pytest

from oeds_post_scripts import cli


def test_backfill_config_path_can_be_set_by_environment(tmp_path):
    config_path = tmp_path / "crawler.yml"
    crawler_data_path = tmp_path / "crawler-data"
    env = dict(
        os.environ,
        OEDS_CRAWLER_CONFIG=str(config_path),
        OEDS_CRAWLER_DATA_DIR=str(crawler_data_path),
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.backfill_entsoe_unavailability import CONFIG_FILE, CRAWLER_DATA_DIR; "
            "print(CONFIG_FILE); print(CRAWLER_DATA_DIR)",
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    output_lines = result.stdout.splitlines()
    assert Path(output_lines[0]) == config_path
    assert Path(output_lines[1]) == crawler_data_path


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


def test_oeds_post_runs_command_main_with_default_and_given_args(monkeypatch, tmp_path):
    observed = []
    module = ModuleType("scripts.gapfill_timeseries")
    module.main = lambda: observed.append((sys.argv[1:], Path.cwd())) or 3
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(sys, "argv", ["oeds-post"])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["gapfill", "entsoe-fms", "--self-test"])

    assert exit_info.value.code == 3
    assert observed == [(["--job", "entsoe_fms", "--self-test"], tmp_path)]
