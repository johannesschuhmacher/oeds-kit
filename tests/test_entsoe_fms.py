import pandas as pd

from crawler.entsoe_fms import EntsoeFMSCrawler


def test_monthly_file_filter_uses_requested_window():
    start = pd.Timestamp("2026-09-03", tz="Europe/Berlin")
    end = pd.Timestamp("2026-09-04", tz="Europe/Berlin")

    assert EntsoeFMSCrawler._file_period_overlaps(
        "2026_09_EnergyPrices.csv", start, end
    )
    assert not EntsoeFMSCrawler._file_period_overlaps(
        "2026_08_EnergyPrices.csv", start, end
    )
    assert not EntsoeFMSCrawler._file_period_overlaps(
        "2026_10_EnergyPrices.csv", start, end
    )
