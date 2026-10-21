from datetime import datetime, timezone

import pandas as pd

from crawler.common.crawler_utils import CrawlerSkipped
from crawler.gie_agsi_alsi import GieAgsiAlsiCrawler


def test_alsi_preserves_energy_and_volume_units_without_changing_agsi():
    crawler = object.__new__(GieAgsiAlsiCrawler)
    timestamp = datetime.now(timezone.utc)
    row = {"gasDayStart": "2026-09-03", "inventory": {"gwh": "2122.65", "lng": "318.9"},
           "dtmi": {"gwh": "5198.93", "lng": "781.07"}, "sendOut": "297", "dtrs": "844"}
    actual = crawler._normalize_rows({"platform": "alsi", "scope": "DE"}, [row], timestamp).iloc[0]
    assert actual.lng_inventory_gwh == 2122.65
    assert actual.lng_inventory_thousand_m3 == 318.9
    assert actual.lng_storage_capacity_gwh == 5198.93
    assert actual.lng_storage_capacity_thousand_m3 == 781.07
    assert actual.lng_send_out_gwh_per_day == 297
    assert actual.lng_send_out_capacity_gwh_per_day == 844
    assert pd.isna(actual.gas_in_storage)
    actual = crawler._normalize_rows({"platform": "agsi", "scope": "DE"},
        [{"gasDayStart": "2026-09-03", "gasInStorage": "120.3"}], timestamp).iloc[0]
    assert actual.gas_in_storage == 120.3
    assert pd.isna(actual.lng_inventory_gwh)


def test_legacy_alsi_volume_is_not_interpreted_as_energy():
    crawler = object.__new__(GieAgsiAlsiCrawler)
    actual = crawler._normalize_rows({"platform": "alsi", "scope": "EU"},
        [{"gasDayStart": "2022-04-04", "inventory": "853.42", "dtmi": "900"}],
        datetime.now(timezone.utc)).iloc[0]
    assert actual.lng_inventory_thousand_m3 == 853.42
    assert actual.lng_storage_capacity_thousand_m3 == 900
    assert pd.isna(actual.lng_inventory_gwh)


def test_missing_api_key_marks_run_as_skipped():
    from unittest.mock import Mock

    import pytest

    crawler = object.__new__(GieAgsiAlsiCrawler)
    crawler.logger = Mock()
    crawler._prepare_schema = Mock()
    crawler._api_key = Mock(return_value=None)

    with pytest.raises(CrawlerSkipped):
        crawler.run()
