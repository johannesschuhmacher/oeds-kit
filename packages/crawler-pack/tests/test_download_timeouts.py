from io import BytesIO
from unittest.mock import Mock
from zipfile import ZipFile

import pandas as pd
import requests

from crawler.ninja import NinjaCrawler
from crawler.power_system_data import PowerSystemDataCrawler
import crawler.power_system_data as power_system_data


def test_ninja_download_passes_timeout(monkeypatch):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("wind.csv", "time,DE_ON\n2016-01-01 00:00:00,0.5\n")
    get = Mock(return_value=Mock(ok=True, content=buffer.getvalue()))
    monkeypatch.setattr(requests, "get", get)

    crawler = object.__new__(NinjaCrawler)
    crawler.logger = Mock()
    crawler.config = {
        "datafiles": {"wind": {"download_url": "https://example.org/wind.zip", "extract_filename": "wind.csv"}}
    }
    crawler.write_to_db = Mock()

    crawler.download_and_write_to_db()

    assert get.call_args.args == ("https://example.org/wind.zip",)
    assert get.call_args.kwargs["timeout"] == 300
    assert crawler.write_to_db.call_args.args[0] == "wind"


def test_power_system_data_download_passes_timeout(monkeypatch):
    csv_bytes = b"id,Name,lat,lon,EIC\n1,Plant,50.0,8.0,X1\n2,NoCoords,,,X2\n"
    get = Mock(return_value=Mock(content=csv_bytes, raise_for_status=Mock()))
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(power_system_data, "etl_run", Mock())

    crawler = object.__new__(PowerSystemDataCrawler)
    crawler.logger = Mock()
    crawler.engine = Mock()
    crawler.schema_name = "power_system_data"
    crawler.table_name = "powersystemdata"
    crawler._init_table_object()
    crawler.metadata.create_all = Mock()
    crawler.set_metadata = Mock()
    crawler._write_to_db = Mock()

    crawler.run()

    assert get.call_args.kwargs["timeout"] == 120
    written = crawler._write_to_db.call_args.args[0]
    assert isinstance(written, pd.DataFrame) and len(written) == 1
    crawler.logger.exception.assert_not_called()
