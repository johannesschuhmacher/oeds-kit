from datetime import datetime, timezone

import pandas as pd

from crawler.netztransparenz import NetztransparenzCrawler


def test_normalize_csv_slot_ends_and_repeated_hour():
    crawler = object.__new__(NetztransparenzCrawler)
    frame = pd.DataFrame(
        {
            "Datum": ["24.10.2026", "25.10.2026", "25.10.2026"],
            "von": ["23:45", "02:45", "02:00"],
            "Zeitzone von": ["UTC", "MESZ", "MEZ"],
            "bis": ["00:00", "02:00", "02:15"],
            "Zeitzone bis": ["UTC", "MEZ", "MEZ"],
            "Wert (MW)": ["1", "2", "3"],
        }
    )

    rows = crawler._normalize_csv({"id": "test"}, frame, datetime(2026, 10, 26, tzinfo=timezone.utc))

    utc = timezone.utc
    assert list(rows["timestamp_from"]) == [
        datetime(2026, 10, 24, 23, 45, tzinfo=utc),
        datetime(2026, 10, 25, 0, 45, tzinfo=utc),
        datetime(2026, 10, 25, 1, 0, tzinfo=utc),
    ]
    assert list(rows["timestamp_to"]) == [
        datetime(2026, 10, 25, 0, 0, tzinfo=utc),
        datetime(2026, 10, 25, 1, 0, tzinfo=utc),
        datetime(2026, 10, 25, 1, 15, tzinfo=utc),
    ]
