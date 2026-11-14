import logging
from unittest.mock import MagicMock

import pytest

from crawler.open_meteo import OpenMeteoCrawler


def test_daily_limit_429_stops_the_run_without_retry_after_sleep():
    crawler = OpenMeteoCrawler.__new__(OpenMeteoCrawler)
    crawler.logger = logging.getLogger("test_open_meteo")
    crawler.batch_size = 2
    crawler.calls_per_minute = 1e9
    crawler.forecast_hours = crawler.past_hours = 1
    crawler.timeout_seconds = 1
    crawler.api_key = None
    crawler._get_locations = lambda: [{"location_id": str(i), "latitude": 50, "longitude": i} for i in range(6)]
    crawler._prepare_schema = crawler._upsert_static_tables = lambda *args: None
    response = MagicMock(status_code=429, text='{"error":true,"reason":"Daily API request limit exceeded."}')
    crawler.session = MagicMock(get=MagicMock(return_value=response))

    with pytest.raises(RuntimeError, match="did not receive any usable"):
        crawler.run()
    assert crawler.session.get.call_count == 1

