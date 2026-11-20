# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests as requests_lib

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


def test_session_caps_a_long_retry_after():
    from urllib3 import HTTPResponse

    from crawler.common.crawler_utils import build_session

    session = build_session(retries=5, backoff_factor=10, retry_statuses=(503,))
    retry = session.get_adapter("https://api.open-meteo.com").max_retries
    response = HTTPResponse(status=503, headers={"Retry-After": "40000"})

    assert retry.get_retry_after(response) == 300
    assert retry.new(total=4).get_retry_after(response) == 300


def _archive_crawler():
    crawler = OpenMeteoCrawler.__new__(OpenMeteoCrawler)
    crawler.logger = logging.getLogger("test_open_meteo")
    crawler.batch_size = 2
    crawler.calls_per_minute = 1e9
    crawler.timeout_seconds = 1
    crawler.api_key = None
    return crawler


def test_fetch_archive_returns_one_row_per_hour_and_lead_time():
    crawler = _archive_crawler()
    hourly = {"time": ["2024-02-01T00:00", "2024-02-01T01:00"]}
    for lead, offset in ((1, 0.0), (2, 10.0)):
        hourly[f"temperature_2m_previous_day{lead}"] = [1.0 + offset, None]
        hourly[f"wind_speed_80m_previous_day{lead}"] = [2.0 + offset, None]
        hourly[f"shortwave_radiation_previous_day{lead}"] = [0.0, None]
    response = MagicMock(status_code=200, json=MagicMock(return_value=[{"hourly": hourly}]))
    crawler.session = MagicMock(get=MagicMock(return_value=response))

    frame = crawler._fetch_archive([{"location_id": "de_52_13", "latitude": 52, "longitude": 13}],
                                   pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-02-01", tz="UTC"))

    # The hour without any value is dropped.
    assert sorted(frame["lead_days"]) == [1, 2]
    assert frame.set_index("lead_days").loc[2, "temperature_2m_c"] == 11.0
    assert (frame["forecast_time"] == pd.Timestamp("2024-02-01T00:00", tz="UTC")).all()


def test_update_archive_continues_after_the_last_stored_day_and_keeps_the_budget(monkeypatch):
    crawler = _archive_crawler()
    crawler.archive_countries = ["DE", "FR"]
    crawler.archive_start = pd.Timestamp("2024-02-01", tz="UTC")
    crawler.archive_calls_per_run = 20
    crawler.previous_day_forecast_table = None
    stored = {"de_1": pd.Timestamp("2026-11-10T23:00", tz="UTC")}
    conn = MagicMock()
    conn.execute.return_value.all.return_value = list(stored.items())
    crawler.engine = MagicMock()
    crawler.engine.begin.return_value.__enter__.return_value = conn
    monkeypatch.setattr("crawler.open_meteo.copy_upsert", lambda *args: None)
    monkeypatch.setattr(pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-19T13:00", tz=tz)))
    requests = []
    crawler._fetch_archive = lambda batch, start, end: requests.append(
        ([location["location_id"] for location in batch], start.date().isoformat(), end.date().isoformat())
    ) or pd.DataFrame()
    locations = [
        {"location_id": "fr_1", "country_code": "FR"},
        {"location_id": "de_1", "country_code": "DE"},
        {"location_id": "de_2", "country_code": "DE"},
        {"location_id": "it_1", "country_code": "IT"},
    ]

    crawler._update_archive(locations)

    # DE comes first; de_1 continues on 11 Nov up to yesterday (1 call). de_2 and fr_1
    # start at archive_start and share requests of 91 days (2 x 6.5 calls); the budget
    # of 20 ends the run after the first of them. it_1 is not in archive_countries.
    assert requests == [
        (["de_1"], "2026-11-11", "2026-11-18"),
        (["de_2", "fr_1"], "2024-02-01", "2024-05-01"),
    ]


def test_update_archive_stops_without_failing_the_run_on_a_timeout(monkeypatch):
    crawler = _archive_crawler()
    crawler.archive_countries = ["DE"]
    crawler.archive_start = pd.Timestamp("2026-11-01", tz="UTC")
    crawler.archive_calls_per_run = 100
    conn = MagicMock()
    conn.execute.return_value.all.return_value = []
    crawler.engine = MagicMock()
    crawler.engine.begin.return_value.__enter__.return_value = conn
    calls = []

    def timeout(batch, start, end):
        calls.append(len(batch))
        raise requests_lib.ReadTimeout("Read timed out.")

    crawler._fetch_archive = timeout
    locations = [{"location_id": f"de_{i}", "country_code": "DE"} for i in range(7)]

    crawler._update_archive(locations)

    # Requests hold at most ARCHIVE_BATCH_SIZE points; the first timeout ends the archive part.
    assert calls == [OpenMeteoCrawler.ARCHIVE_BATCH_SIZE]
