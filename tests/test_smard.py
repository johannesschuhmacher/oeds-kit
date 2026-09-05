import pandas as pd
import pytest

from crawler.smard import SmardCrawler


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
