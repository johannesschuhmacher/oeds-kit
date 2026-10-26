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


def test_operational_chunk_replaces_returned_records_by_id(monkeypatch):
    # A gas day across the end of summer time (25 hours) plus a firm technical
    # capacity valid since 2011, which the API returns in every chunk. Only the
    # returned ids are replaced, so neither earlier hours nor the old capacity's
    # other copies elsewhere are deleted; a repeated id is written once.
    crawler = object.__new__(EntsogCrawler)
    crawler.schema_name = "entsog"
    crawler.engine = MagicMock()
    crawler._delete_records = Mock()
    monkeypatch.setattr("crawler.entsog.inspect", lambda engine: Mock(has_table=Mock(return_value=True)))
    written = []
    monkeypatch.setattr(pd.DataFrame, "to_sql", lambda frame, *args, **kwargs: written.append(frame.copy()))
    periodfrom = list(pd.date_range("2026-10-24 06:00", periods=25, freq="h", tz="Europe/Berlin"))
    periodfrom.append(pd.Timestamp("2011-01-01 06:00", tz="Europe/Berlin"))
    frame = pd.DataFrame(
        {
            "id": [f"r{i}" for i in range(26)] + ["r25"],
            "periodfrom": [ts.isoformat() for ts in periodfrom] + [periodfrom[-1].isoformat()],
            "periodto": [(ts + pd.Timedelta(hours=1)).isoformat() for ts in periodfrom] + ["2027-01-01T06:00:00+01:00"],
        }
    )

    crawler._write_operational_chunk("firm_technical", frame)

    crawler._delete_records.assert_called_once_with("firm_technical", [f"r{i}" for i in range(26)])
    assert written[0]["id"].tolist() == [f"r{i}" for i in range(26)]
