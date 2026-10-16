import pandas as pd
import pytest
from unittest.mock import Mock
from sqlalchemy import MetaData, UniqueConstraint

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


def test_newest_file_library_version_is_used():
    crawler = object.__new__(EntsoeFMSCrawler)
    crawler.logger = Mock()
    crawler._available_folders = [
        "EnergyPrices_12.1.D_r3",
        "EnergyPrices_12.1.D_r3.1",
        "RedispatchingInternal_13.1.A_r3.2",
        "RedispatchingInternal_13.1.A_r3.10",
        "TransmissionAssets",
    ]

    assert crawler._resolve_folder("EnergyPrices_12.1.D") == "EnergyPrices_12.1.D_r3.1"
    # Older configurations still name the versioned folder.
    assert crawler._resolve_folder("EnergyPrices_12.1.D_r3") == "EnergyPrices_12.1.D_r3.1"
    assert crawler._resolve_folder("RedispatchingInternal_13.1.A") == "RedispatchingInternal_13.1.A_r3.10"
    assert crawler._resolve_folder("TransmissionAssets") == "TransmissionAssets"
    with pytest.raises(LookupError):
        crawler._resolve_folder("ActualTotalLoad_6.1.A")


def test_every_active_table_has_matching_unique_key_and_constraint(monkeypatch):
    created = []
    monkeypatch.setattr(MetaData, "create_all", lambda metadata, engine, tables: created.append(metadata))
    crawler = object.__new__(EntsoeFMSCrawler)
    crawler.engine = Mock()
    crawler.logger = Mock()

    for table_name in EntsoeFMSCrawler.DATA_ITEM_TABLE_MAP.values():
        crawler._create_table_with_unique_constraint(table_name)
        table = created[-1].tables[f"entsoe_fms.{table_name}"]
        constraint = next(c for c in table.constraints if isinstance(c, UniqueConstraint))

        assert constraint.name == EntsoeFMSCrawler.UNIQUE_KEY_DICT[table_name]
        assert {c.name for c in constraint.columns} == set(EntsoeFMSCrawler.UNIQUE_KEY_COLUMNS[table_name]), table_name
