import pandas as pd
import pytest

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
