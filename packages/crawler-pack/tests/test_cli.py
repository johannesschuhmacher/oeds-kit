import pytest
import yaml

from crawler import cli
from crawler.common.crawler_config import effective_crawler_config
from crawler.common.crawler_utils import CrawlerSkipped

RAW = {
    "default": {
        "enable": False,
        "schedule": "0 4 * * *",
        "database_uri": "postgresql://u:p@db/x?options=",
        "email": {"mailhost": ""},
    },
    "smard": {"enable": True, "schema_name": "smard", "post_run_scripts": ["oeds-post gapfill smard"]},
    "entsoe_fms": {
        "enable": True,
        "default_start_date": "2014-01-01",
        "jobs": {
            "latest_hourly": {
                "enable": True,
                "schedule": "0 * * * *",
                "fms_package_window_months": 1,
                "run_post_scripts": True,
            }
        },
    },
}


def test_effective_config_merges_default_section_and_job():
    config = effective_crawler_config(RAW, "entsoe_fms", "latest_hourly")

    assert config["fms_package_window_months"] == 1
    assert config["default_start_date"] == "2014-01-01"
    assert config["email"] == {"mailhost": ""}
    assert config["db_uri"] == config["database_uri"] == RAW["default"]["database_uri"]
    assert config["_scheduler_job_id"] == "entsoe_fms:latest_hourly"
    assert config["schema_name"] == "entsoe_fms"
    assert not {"enable", "schedule", "jobs", "run_post_scripts"} & set(config)


def test_effective_config_without_job_uses_section_and_drops_scheduler_keys():
    config = effective_crawler_config(RAW, "smard")

    assert config["_scheduler_job_id"] == "smard:default"
    assert "post_run_scripts" not in config and "enable" not in config


def test_unknown_crawler_or_job_is_an_error():
    with pytest.raises(KeyError):
        effective_crawler_config(RAW, "nope")
    with pytest.raises(KeyError):
        effective_crawler_config(RAW, "entsoe_fms", "nope")


def test_entry_points_register_the_pack_crawlers():
    entries = cli.crawler_entry_points()
    assert {"smard", "entsoe_fms", "mastr"} <= set(entries)
    assert cli.load_crawler_class("smard").__name__ == "SmardCrawler"


@pytest.mark.parametrize(
    "outcome, expected",
    [(None, cli.EXIT_OK), (CrawlerSkipped("no key"), cli.EXIT_SKIPPED), (RuntimeError("boom"), cli.EXIT_FAILED)],
)
def test_exit_codes(tmp_path, monkeypatch, outcome, expected):
    config_path = tmp_path / "CRAWLER_CONFIG.yml"
    config_path.write_text(yaml.safe_dump(RAW), encoding="utf-8")

    class FakeCrawler:
        def __init__(self, name, config):
            assert name == "smard" and config["schema_name"] == "smard"

        def run(self):
            if outcome is not None:
                raise outcome

    monkeypatch.setattr(cli, "load_crawler_class", lambda name: FakeCrawler)
    assert cli.main(["smard", "--config", str(config_path)]) == expected


def test_list_does_not_need_a_config(capsys):
    assert cli.main(["--list", "--config", "does-not-exist.yml"]) == cli.EXIT_OK
    assert "smard" in capsys.readouterr().out


def test_failed_run_is_logged_critical_on_the_crawler_logger(tmp_path, monkeypatch, caplog):
    import logging

    config_path = tmp_path / "CRAWLER_CONFIG.yml"
    config_path.write_text(yaml.safe_dump(RAW), encoding="utf-8")

    class FailingCrawler:
        def __init__(self, name, config):
            pass

        def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(cli, "load_crawler_class", lambda name: FailingCrawler)
    with caplog.at_level(logging.CRITICAL, logger="smard"):
        assert cli.main(["smard", "--config", str(config_path)]) == cli.EXIT_FAILED
    records = [r for r in caplog.records if r.name == "smard" and r.levelno == logging.CRITICAL]
    assert records and records[0].exc_info is not None
