# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

import pandas as pd
import pytest
import requests

from crawler.common.kit_base import KitCrawler
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


def test_entsoe_clients_retry_http_599(monkeypatch):
    # intern, 2026-11-27: one 599 answer failed the whole load_forecast_versions run.
    def fake_init(self, crawler_name, config):
        self.config = config
        self.schema_name = crawler_name

    monkeypatch.setattr(KitCrawler, "__init__", fake_init)
    monkeypatch.setenv("ENTSOE_API_KEY", "test-token")

    crawler = EntsoeApiCrawler("entsoe_api", {})

    for client in (crawler.pandas_client, crawler.raw_client):
        retry = client.session.get_adapter("https://web-api.tp.entsoe.eu/api").max_retries
        assert 599 in retry.status_forcelist
        assert retry.total >= 1


def test_run_keeps_the_security_token_out_of_the_error(monkeypatch):
    crawler = object.__new__(EntsoeApiCrawler)
    url = "https://web-api.tp.entsoe.eu/api?documentType=A65&securityToken=secret-123&periodStart=1"

    def fail():
        raise requests.HTTPError(f"599 Server Error: status code 599 for url: {url}")

    monkeypatch.setattr(crawler, "_refresh_all", fail, raising=False)

    with pytest.raises(requests.HTTPError) as excinfo:
        crawler.run()

    assert "secret-123" not in str(excinfo.value)
    assert "securityToken=***&periodStart=1" in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
