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
