import io
from zipfile import ZipFile

import pandas as pd

from crawler.epex_spot import EpexSpotCrawler


def test_trade_archive_is_read_in_blocks_without_losing_records():
    payload = io.BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("trades.csv", "# Published 2025-01-01T12:00:00Z\n"
                         "TradeId,OrderID,DeliveryStart,DeliveryEnd,Price,Volume\n"
                         "001,010,2025-01-01T00:00:00Z,2025-01-01T00:15:00Z,-5,2\n"
                         "002,011,2025-01-01T00:15:00Z,2025-01-01T00:30:00Z,10,3\n"
                         "003,012,2025-01-01T00:30:00Z,2025-01-01T00:45:00Z,15,4\n")
    crawler = object.__new__(EpexSpotCrawler)
    crawler.config = {"database_batch_size": 2}

    blocks = list(crawler._parse_continuous_trades_zip(payload.getvalue(), "trades.zip"))

    assert [len(block) for block in blocks] == [2, 1]
    frame = pd.concat(blocks, ignore_index=True)
    assert frame.trade_id.tolist() == ["001", "002", "003"]
    assert frame.price.tolist() == [-5, 10, 15]
    assert frame.volume.sum() == 9
    assert str(frame.delivery_start_utc.dt.tz) == "UTC"
    assert frame.source_file.tolist() == ["trades.zip"] * 3


def test_unchanged_remote_files_are_not_downloaded_again():
    from types import SimpleNamespace
    from unittest.mock import Mock

    crawler = object.__new__(EpexSpotCrawler)
    crawler.logger = Mock()
    old = SimpleNamespace(filename="Continuous_Trades-DE-20260224-20260225T001117027Z.csv.zip",
                          st_size=100, st_mtime=1700000000)
    new = SimpleNamespace(filename="Continuous_Trades-DE-20260225-20260226T001030985Z.csv.zip",
                          st_size=200, st_mtime=1700086400)
    crawler._list_remote_files = Mock(return_value=[old, new])
    crawler._imported_file_keys = Mock(return_value={(f"/trades/{old.filename}", 100, 1700000000)})
    crawler._download_bytes = Mock(return_value=b"payload")
    crawler._filter_delivery_start = Mock(side_effect=lambda frame, start: frame)
    crawler._upsert_dataframe = Mock(return_value=3)
    crawler._mark_imported = Mock()

    rows = crawler._import_remote_files("/trades", "continuous_trades", lambda payload, name: pd.DataFrame({"a": [1, 2, 3]}),
                                        "unique_epex_continuous_trades", pd.Timestamp("2026-01-01", tz="UTC"))

    assert rows == 3
    crawler._download_bytes.assert_called_once_with(f"/trades/{new.filename}")
    crawler._mark_imported.assert_called_once_with(f"/trades/{new.filename}", new, 3)
