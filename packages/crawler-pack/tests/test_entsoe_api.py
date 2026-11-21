# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

import pandas as pd

from crawler.entsoe_api import EntsoeApiCrawler


class _FrozenTimestamp(pd.Timestamp):
    @classmethod
    def now(cls, tz=None):
        # First run after the end of summer time (25 Oct 2026, 25-hour day).
        return pd.Timestamp("2026-10-26 11:35", tz="UTC").tz_convert(tz)


def test_query_window_starts_and_ends_at_local_midnight_across_dst(monkeypatch):
    crawler = object.__new__(EntsoeApiCrawler)
    crawler.config = {"lookback_days": 1, "lookahead_days": 2}
    monkeypatch.setattr(pd, "Timestamp", _FrozenTimestamp)

    start, end = crawler._query_window()

    assert start == pd.Timestamp("2026-10-24 22:00", tz="UTC")
    assert end == pd.Timestamp("2026-10-27 23:00", tz="UTC")


def test_load_forecast_versions_are_stored_per_country_in_their_own_table(monkeypatch):
    crawler = object.__new__(EntsoeApiCrawler)
    crawler.config = {
        "country_codes": ["FR", "BE"],
        "target_datasets": ["load_forecast_versions"],
        "lookback_days": 0,
        "request_pause_seconds": 0,
    }
    calls = []
    monkeypatch.setattr(crawler, "_ensure_tables", lambda: None, raising=False)
    monkeypatch.setattr(crawler, "set_metadata", lambda metadata: None, raising=False)
    crawler.logger = logging.getLogger("test")
    crawler.schema_name = "entsoe_api"
    monkeypatch.setattr(
        crawler,
        "_refresh_load_forecast",
        lambda country, process, start, end, table="load_forecasts", constraint=None: calls.append((country, table)) or 0,
    )

    crawler.run()

    assert calls == [("FR", "load_forecast_versions"), ("BE", "load_forecast_versions")]
