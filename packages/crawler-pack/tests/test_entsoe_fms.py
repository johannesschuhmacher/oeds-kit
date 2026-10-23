import pandas as pd
import pytest
from unittest.mock import MagicMock, Mock
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
    crawler._ensure_update_time_index = Mock()
    crawler._known_columns = {}
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


def _fake_crawler(**attrs):
    crawler = object.__new__(EntsoeFMSCrawler)
    crawler.logger = Mock()
    crawler._reflected_tables = {}
    crawler._known_columns = {}
    crawler._update_time_index_checked = set()
    for name, value in attrs.items():
        setattr(crawler, name, value)
    return crawler


def _begin_returning(conn):
    from contextlib import contextmanager

    return contextmanager(lambda: iter([conn]))


def test_c_parser_and_iso_timestamps_match_previous_parsing(tmp_path):
    """sep='\\t' (C engine) + ISO8601 must give the same frame as the regex/python/mixed path."""
    import csv

    n = 200_000
    base = pd.Timestamp("2026-09-01 00:00:00")
    rows = []
    for i in range(n):
        ts = base + pd.Timedelta(minutes=15 * i)
        rows.append("\t".join([
            ts.strftime("%Y-%m-%d %H:%M:%S") + (".000" if i % 3 == 0 else ""),
            "PT15M",
            f"10Y{i % 50:04d}",
            'Unit "A" ' + str(i % 7) if i % 11 else "",
            "" if i % 13 == 0 else f"{i * 0.25:.2f}",
            str(i % 1000),
            (ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        ]))
    header = "\t".join([
        "DateTime(UTC)", "ResolutionCode", "AreaCode", "GenerationUnitName", "ActualGenerationOutput[MW]",
        "Sequence", "UpdateTime(UTC)",
    ])
    path = tmp_path / "sample.csv"
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    old = pd.read_csv(path, sep=r"\t", engine="python")
    new = pd.read_csv(path, sep="\t", quoting=csv.QUOTE_NONE)
    pd.testing.assert_frame_equal(old, new)

    for col in ("DateTime(UTC)", "UpdateTime(UTC)"):
        old[col] = pd.to_datetime(old[col], format="mixed").dt.tz_localize("UTC")
    new = EntsoeFMSCrawler._normalize_timestamp_columns(new)
    pd.testing.assert_frame_equal(old, new)


def test_iso_parser_falls_back_to_mixed_for_non_iso_values():
    df = pd.DataFrame({"UpdateTime(UTC)": ["15/09/2026 10:00", "16/09/2026 11:30"]})
    out = EntsoeFMSCrawler._normalize_timestamp_columns(df)
    assert out["UpdateTime(UTC)"].tolist() == [
        pd.Timestamp("2026-09-15 10:00", tz="UTC"),
        pd.Timestamp("2026-09-16 11:30", tz="UTC"),
    ]


def _upsert_capture(monkeypatch, crawler, table, df):
    copy_upsert = Mock()
    monkeypatch.setattr("crawler.entsoe_fms.copy_upsert", copy_upsert)
    crawler.engine = Mock()
    crawler._reflected_tables[table.name] = table
    crawler._upsert_dataframe(table.name, df)
    return copy_upsert.call_args.args


def test_upsert_only_rewrites_rows_with_newer_update_time(monkeypatch):
    from sqlalchemy import Column, DateTime, Float, String, Table

    table = Table(
        "EnergyPrices", MetaData(schema="entsoe_fms"),
        Column("DateTime(UTC)", DateTime(timezone=True)), Column("AreaCode", String),
        Column("Price[Currency/MWh]", Float), Column("UpdateTime(UTC)", DateTime(timezone=True)),
        UniqueConstraint("DateTime(UTC)", "AreaCode", name="unique_energy_prices"),
    )
    crawler = _fake_crawler()
    crawler.UNIQUE_KEY_DICT = {"EnergyPrices": "unique_energy_prices"}
    crawler.UNIQUE_KEY_COLUMNS = {"EnergyPrices": ["DateTime(UTC)", "AreaCode"]}
    df = pd.DataFrame({
        "DateTime(UTC)": pd.to_datetime(["2026-09-15 00:00", "2026-09-15 00:00"], utc=True),
        "AreaCode": ["DE", "DE"],
        "Price[Currency/MWh]": [11.0, 10.0],
        "UpdateTime(UTC)": pd.to_datetime(["2026-09-17", "2026-09-16"], utc=True),
    })

    _, target, frame, constraint, keys, where = _upsert_capture(monkeypatch, crawler, table, df)
    assert target is table
    assert (constraint, keys) == ("unique_energy_prices", ["DateTime(UTC)", "AreaCode"])
    assert where == (
        '"entsoe_fms"."EnergyPrices"."UpdateTime(UTC)" IS NULL '
        'OR "entsoe_fms"."EnergyPrices"."UpdateTime(UTC)" < EXCLUDED."UpdateTime(UTC)"'
    )
    # Of duplicate keys the row with the newest UpdateTime is kept.
    assert frame["Price[Currency/MWh]"].tolist() == [11.0]


def test_upsert_without_update_time_column_updates_unconditionally(monkeypatch):
    from sqlalchemy import Column, Float, String, Table

    table = Table(
        "TransmissionAssets", MetaData(schema="entsoe_fms"),
        Column("AssetCode", String), Column("Capacity", Float),
        UniqueConstraint("AssetCode", name="unique_transmission_assets"),
    )
    crawler = _fake_crawler()
    crawler.UNIQUE_KEY_DICT = {"TransmissionAssets": "unique_transmission_assets"}
    crawler.UNIQUE_KEY_COLUMNS = {"TransmissionAssets": ["AssetCode"]}
    df = pd.DataFrame({"AssetCode": ["A"], "Capacity": [1.0]})

    assert _upsert_capture(monkeypatch, crawler, table, df)[-1] is None


def test_insert_conflict_falls_back_to_upsert():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    pd.DataFrame({"AssetCode": ["A"], "Capacity": [1.0]}).to_sql("TransmissionAssets", engine, index=False)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE UNIQUE INDEX unique_transmission_assets ON "TransmissionAssets" ("AssetCode")')
    crawler = _fake_crawler(engine=engine, _upsert_dataframe=Mock())
    crawler.UNIQUE_KEY_COLUMNS = {"TransmissionAssets": ["AssetCode"]}

    crawler._insert_dataframe("TransmissionAssets", pd.DataFrame({"AssetCode": ["A", "B"], "Capacity": [2.0, 3.0]}))

    assert crawler._upsert_dataframe.call_args.args[1]["AssetCode"].tolist() == ["A", "B"]


def test_add_missing_columns_queries_information_schema_once_per_file():
    conn = Mock()
    crawler = _fake_crawler(engine=Mock())
    crawler.engine.begin = _begin_returning(conn)
    crawler._table_columns = Mock(return_value=["DateTime(UTC)", "AreaCode"])
    chunk = pd.DataFrame({"DateTime(UTC)": pd.to_datetime(["2026-09-15"], utc=True), "AreaCode": ["DE"]})

    for _ in range(3):  # three chunks of one file
        crawler._add_missing_columns("EnergyPrices", chunk)
    assert crawler._table_columns.call_count == 1
    assert conn.execute.call_count == 0

    # A new column is added once and remembered for the following chunks.
    crawler._reflected_tables["EnergyPrices"] = object()
    wider = chunk.assign(**{"Price[Currency/MWh]": [1.5]})
    crawler._add_missing_columns("EnergyPrices", wider)
    crawler._add_missing_columns("EnergyPrices", wider)
    assert crawler._table_columns.call_count == 1
    assert conn.execute.call_count == 1
    assert 'ADD COLUMN IF NOT EXISTS "Price[Currency/MWh]" DOUBLE PRECISION' in str(conn.execute.call_args.args[0])
    assert "EnergyPrices" not in crawler._reflected_tables  # reflected table invalidated

    crawler._known_columns.pop("EnergyPrices", None)  # next file
    crawler._add_missing_columns("EnergyPrices", chunk)
    assert crawler._table_columns.call_count == 2


def test_download_file_streams_body_to_disk(tmp_path):
    response = Mock()
    response.iter_content = Mock(return_value=iter([b"abc", b"def"]))
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    crawler = _fake_crawler(session=Mock())
    crawler.session.post = Mock(return_value=response)

    target = tmp_path / "file.csv"
    crawler._download_file("id-1", str(target))

    assert crawler.session.post.call_args.kwargs["stream"] is True
    assert crawler.session.post.call_args.kwargs["timeout"] == 120
    assert target.read_bytes() == b"abcdef"


def test_save_power_system_data_downloads_with_timeout(monkeypatch):
    import requests

    csv_bytes = b"id,Name,lat,lon,EIC\n1,Plant,50.0,8.0,X1\n2,NoCoords,,,X2\n"
    get = Mock(return_value=Mock(content=csv_bytes, raise_for_status=Mock()))
    monkeypatch.setattr(requests, "get", get)
    written = []
    monkeypatch.setattr(pd.DataFrame, "to_sql", lambda self, *args, **kwargs: written.append(len(self)))
    crawler = _fake_crawler(engine=MagicMock())
    crawler._table_columns = Mock(return_value=[])

    crawler.save_power_system_data()

    assert get.call_args.kwargs["timeout"] == 120
    assert written == [1]  # row without coordinates dropped
    crawler.logger.error.assert_not_called()


def test_new_tables_index_update_time(monkeypatch):
    created = []
    monkeypatch.setattr(MetaData, "create_all", lambda metadata, engine, tables: created.append(metadata))
    crawler = _fake_crawler(engine=Mock())

    for table_name in EntsoeFMSCrawler.DATA_ITEM_TABLE_MAP.values():
        crawler._create_table_with_unique_constraint(table_name)
        table = created[-1].tables[f"entsoe_fms.{table_name}"]
        indexes = list(table.indexes)
        if "UpdateTime(UTC)" in table.c:
            assert [index.name for index in indexes] == [f"ix_{table_name}_updatetime"[:63]], table_name
            assert len(indexes[0].name) <= 63
            assert [c.name for c in indexes[0].columns] == ["UpdateTime(UTC)"]
        else:
            assert indexes == [], table_name


def test_existing_table_update_time_index_is_created_once_per_run():
    conn = Mock()
    conn.execute.return_value.scalar.return_value = None  # index does not exist yet
    crawler = _fake_crawler(engine=Mock())
    crawler.engine.begin = _begin_returning(conn)
    crawler._table_columns = Mock(return_value=["DateTime(UTC)", "UpdateTime(UTC)"])

    crawler._ensure_update_time_index("EnergyPrices")
    crawler._ensure_update_time_index("EnergyPrices")

    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert statements == [
        "SELECT to_regclass(:name)",
        'CREATE INDEX IF NOT EXISTS "ix_EnergyPrices_updatetime" ON "entsoe_fms"."EnergyPrices" ("UpdateTime(UTC)")',
    ]
