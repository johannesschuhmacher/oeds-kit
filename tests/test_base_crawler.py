import logging
from unittest.mock import patch

from crawler.common.base_crawler import BaseCrawler
from crawler.common.kit_base import KitCrawler


class _Crawler(BaseCrawler):
    def run(self):
        pass


def test_base_crawler_alias_is_kit_crawler():
    assert BaseCrawler is KitCrawler


def test_unwritable_log_file_does_not_abort_construction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {"database_uri": "sqlite:///", "schema_name": "unit_test"}
    with patch(
        "crawler.common.crawler_logging.RotatingFileHandler", side_effect=PermissionError("denied")
    ):
        crawler = _Crawler("unit_test_crawler", config)

    assert not any(isinstance(h, logging.FileHandler) for h in crawler.logger.handlers)
