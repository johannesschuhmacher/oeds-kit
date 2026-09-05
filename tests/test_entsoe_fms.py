import pandas as pd
import pytest
from unittest.mock import Mock

from crawler.entsoe_fms import EntsoeFMSCrawler


def test_monthly_file_filter_uses_requested_window():
    start = pd.Timestamp("2026-09-03", tz="Europe/Berlin")
    end = pd.Timestamp("2026-09-04", tz="Europe/Berlin")

    assert EntsoeFMSCrawler._file_period_overlaps(
        "2026_09_EnergyPrices.csv", start, end
    )
    assert not EntsoeFMSCrawler._file_period_overlaps(
        "2026_08_EnergyPrices.csv", start, end
    )
    assert not EntsoeFMSCrawler._file_period_overlaps(
        "2026_10_EnergyPrices.csv", start, end
    )


def test_run_uses_runtime_directory_and_reports_failure(monkeypatch):
    crawler = object.__new__(EntsoeFMSCrawler)
    crawler.config = {'fms_package_window_months': 1}
    crawler.logger = Mock()
    crawler.save_power_system_data = Mock()
    crawler.fetch_from_entsoe_fms_to_database = Mock(side_effect=RuntimeError('download failed'))
    monkeypatch.setenv('OEDS_CRAWLER_DATA_DIR', '/tmp/crawler-downloads')
    with pytest.raises(RuntimeError, match='download failed'):
        crawler.run()
    assert crawler.fetch_from_entsoe_fms_to_database.call_args.args[0] == '/tmp/crawler-downloads'
