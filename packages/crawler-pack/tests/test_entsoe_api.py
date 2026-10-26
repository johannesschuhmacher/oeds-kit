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
