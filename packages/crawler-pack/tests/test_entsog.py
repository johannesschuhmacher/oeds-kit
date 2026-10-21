from unittest.mock import Mock

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
