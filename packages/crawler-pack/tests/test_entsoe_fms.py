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


def test_incremental_watermark_is_read_once_per_data_item(tmp_path):
    """Re-reading MAX(UpdateTime) after every file dropped rows of the next file."""
    header = "\t".join([
        "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaDisplayName", "AreaTypeCode", "AreaMapCode",
        "ContractType", "Sequence", "Price[Currency/MWh]", "Currency", "UpdateTime(UTC)",
    ])
    row = "\t".join(["2026-09-15 00:00:00", "PT60M", "10Y", "DE-LU", "BZN", "DE_LU", "DA", "1", "10.0", "EUR",
                     "2026-09-16 00:00:00"])

    crawler = object.__new__(EntsoeFMSCrawler)
    crawler.logger = Mock()
    crawler.config = {"target_data_items": ["EnergyPrices_12.1.D"]}
    crawler._authenticate = Mock()
    crawler._migrate_renamed_columns = Mock()
    crawler._ensure_nulls_not_distinct = Mock()
    files = ["2026_09_EnergyPrices_12.1.D_r3.1.csv", "2026_10_EnergyPrices_12.1.D_r3.1.csv"]
    crawler._list_metadata = Mock(return_value=[{"name": name, "fileId": name} for name in files])
    crawler._get_table_state = Mock(return_value={
        "table_exists": True,
        "update_time_column": "UpdateTime(UTC)",
        "datetime_column_name": "DateTime(UTC)",
        "last_update_time": pd.Timestamp("2026-09-01"),
        "last_date_time": pd.Timestamp("2026-09-01"),
    })
    crawler._download_file = Mock(side_effect=lambda file_id, target: open(target, "w").write(header + "\n" + row + "\n"))
    crawler._add_missing_columns = Mock()
    crawler._flush_to_database = Mock()

    crawler._download_files_and_write_into_database(
        str(tmp_path),
        pd.Timestamp("2026-09-01", tz="Europe/Berlin"),
        pd.Timestamp("2026-10-20", tz="Europe/Berlin"),
    )

    assert crawler._get_table_state.call_count == 1
    assert crawler._flush_to_database.call_count == len(files)
