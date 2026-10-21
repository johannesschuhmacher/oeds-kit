from datetime import datetime, timezone
from unittest.mock import Mock

from crawler.tradinghub import TradingHubCrawler


PRELIMINARY_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<PreliminaryImbalancePrices xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <PreliminaryImbalancePrices>
    <NegativeDailyImbalancePriceYesterdayDate>2026-10-21T05:00:00</NegativeDailyImbalancePriceYesterdayDate>
    <NegativeDailyImbalancePriceYesterday>87.907</NegativeDailyImbalancePriceYesterday>
  </PreliminaryImbalancePrices>
</PreliminaryImbalancePrices>
"""


def _crawler_with_response(content: bytes) -> tuple[TradingHubCrawler, Mock]:
    crawler = object.__new__(TradingHubCrawler)
    crawler.timeout_seconds = 5
    response = Mock(content=content, url="https://api.tradinghub.eu/x")
    crawler.session = Mock(get=Mock(return_value=response))
    return crawler, crawler.session.get


def test_dated_report_uses_dataexport_path_and_iso_gas_days():
    crawler, get = _crawler_with_response(b"<MarketAreaMonitor><MarketAreaMonitor><Gasday>2026-10-20</Gasday><Norway>1416</Norway></MarketAreaMonitor></MarketAreaMonitor>")
    _, records = crawler._fetch_report(
        "MarketAreaMonitor",
        datetime(2026, 9, 6, tzinfo=timezone.utc),
        datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    assert get.call_args.args == ("https://api.tradinghub.eu/api/dataexport/xmlexport/MarketAreaMonitor",)
    assert get.call_args.kwargs["params"] == {"startDate": "2026-09-06", "endDate": "2026-10-21"}
    assert records == [{"Gasday": "2026-10-20", "Norway": "1416"}]


def test_running_gas_day_report_has_no_date_range_and_accepts_other_record_tag():
    crawler, get = _crawler_with_response(PRELIMINARY_XML)
    _, records = crawler._fetch_report(
        "PricesEnergyImbalancePreliminary",
        datetime(2026, 9, 6, tzinfo=timezone.utc),
        datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    assert get.call_args.kwargs["params"] == {}
    assert records[0]["NegativeDailyImbalancePriceYesterday"] == "87.907"
