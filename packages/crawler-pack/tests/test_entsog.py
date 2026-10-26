from unittest.mock import MagicMock, Mock

import pandas as pd

from crawler.entsog import EntsogCrawler


def test_reference_collection_does_not_use_api_default_page_limit():
    crawler = object.__new__(EntsogCrawler)
    crawler.session = Mock()
    crawler.session.get.return_value.json.return_value = {
        "operators": [{"operatorKey": f"operator-{index}"} for index in range(101)]
    }

    frame = crawler._fetch_collection("operators", "operators")

    assert crawler.session.get.call_args.kwargs["params"]["limit"] == -1
    assert len(frame) == 101
    assert frame.iloc[-1]["operatorkey"] == "operator-100"


def test_operational_chunk_deletes_only_the_fetched_gas_day(monkeypatch):
    # Gas day 24 Oct 2026 (end of summer time): 06:00 CEST to 06:00 CET, 25 hours.
    crawler = object.__new__(EntsogCrawler)
    crawler.schema_name = "entsog"
    crawler.engine = MagicMock()
    crawler._delete_chunk = Mock()
    monkeypatch.setattr(pd.DataFrame, "to_sql", Mock())
    periodfrom = pd.date_range("2026-10-24 06:00", periods=25, freq="h", tz="Europe/Berlin")
    frame = pd.DataFrame(
        {
            "periodfrom": [ts.isoformat() for ts in periodfrom],
            "periodto": [(ts + pd.Timedelta(hours=1)).isoformat() for ts in periodfrom],
        }
    )

    crawler._write_operational_chunk("physical_flow", frame)

    crawler._delete_chunk.assert_called_once_with(
        "physical_flow",
        pd.Timestamp("2026-10-24 04:00", tz="UTC"),
        pd.Timestamp("2026-10-25 04:00", tz="UTC"),
    )
