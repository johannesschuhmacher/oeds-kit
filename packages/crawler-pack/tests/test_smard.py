# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import pandas as pd
import pytest
from unittest.mock import Mock

from crawler.smard import SmardCrawler
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("timestamp,expected", [
    ("2026-09-02T00:00:00Z", "2026-08-30T22:00:00Z"),
    ("2026-01-07T00:00:00Z", "2026-01-04T23:00:00Z"),
    ("2026-03-29T20:00:00Z", "2026-03-22T23:00:00Z"),
    ("2026-03-29T22:00:00Z", "2026-03-29T22:00:00Z"),
    ("2026-10-25T21:00:00Z", "2026-10-18T22:00:00Z"),
    ("2026-10-25T23:00:00Z", "2026-10-25T23:00:00Z"),
])
def test_chart_week_start_uses_german_calendar(timestamp, expected):
    assert SmardCrawler._week_start(pd.Timestamp(timestamp)) == pd.Timestamp(expected)


def test_metadata_uses_stored_coverage_and_actual_schema():
    crawler = object.__new__(SmardCrawler)
    crawler.engine = create_engine("sqlite://")
    crawler.schema_name = "test_smard"
    captured = {}
    crawler.set_metadata = captured.update
    with crawler.engine.begin() as conn:
        conn.execute(text("CREATE TABLE smard (timestamp text)"))
        conn.execute(text("CREATE TABLE prices (timestamp text)"))
        conn.execute(text("INSERT INTO smard VALUES ('2026-09-01 00:00:00')"))
        conn.execute(text("INSERT INTO prices VALUES ('2026-09-05 12:00:00')"))
    crawler.update_metadata()
    assert captured["schema_name"] == "test_smard"
    assert captured["temporal_start"] == "2026-09-01 00:00:00"
    assert captured["temporal_end"] == "2026-09-05 12:00:00"
    assert captured["data_date"] == pd.Timestamp.now(tz="UTC").date().isoformat()


def test_run_repeats_weekly_passes_until_caught_up():
    crawler = object.__new__(SmardCrawler)
    crawler.logger = Mock()
    crawler.create_table = lambda: None
    crawler.update_metadata = lambda: None
    passes = iter([96, 96, 12, 0])
    calls = []
    crawler.feed = lambda: calls.append(1) or next(passes)

    crawler.run()

    assert len(calls) == 4


def _crawler_with_404(monkeypatch, start_date):
    import requests
    from crawler import smard

    response = requests.Response()
    response.status_code = 404
    response.url = "https://www.smard.de/app/chart_data/x.json"
    session = Mock()
    session.get.return_value = response
    monkeypatch.setattr(smard, "build_session", lambda **kwargs: session)
    monkeypatch.setattr(smard, "REQUEST_PAUSE_SECONDS", 0)
    crawler = object.__new__(SmardCrawler)
    crawler.select_latest = lambda commodity_id: (start_date, start_date)
    return crawler


def test_missing_file_for_future_week_is_not_an_error(monkeypatch, caplog):
    # Sunday morning: the current week is complete, next week's file starts at Monday 00:00.
    future_week = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=20)
    crawler = _crawler_with_404(monkeypatch, future_week)

    assert list(crawler.get_data_per_commodity()) == []
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


def test_missing_file_for_past_week_is_an_error(monkeypatch, caplog):
    past_week = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)
    crawler = _crawler_with_404(monkeypatch, past_week)

    assert list(crawler.get_data_per_commodity()) == []
    assert [r for r in caplog.records if r.levelname == "ERROR"]
