import logging
from unittest.mock import patch

import pytest

from crawler.common.kit_base import KitCrawler, kit_db_uri

PACK_URI = "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path="


def test_kit_db_uri_appends_placeholder_so_upstream_format_yields_pack_uri():
    uri = kit_db_uri({"database_uri": PACK_URI})
    assert uri == PACK_URI + "{DBNAME}"
    assert uri.format(DBNAME="smard") == PACK_URI + "smard"


def test_kit_db_uri_keeps_existing_placeholder():
    uri = "postgresql://opendata:opendata@localhost:6432/{DBNAME}"
    assert kit_db_uri({"db_uri": uri}) == uri


def test_kit_db_uri_escapes_literal_braces():
    uri = kit_db_uri({"database_uri": "sqlite:///{weird}.db?schema="})
    assert uri == "sqlite:///{{weird}}.db?schema={DBNAME}"
    assert uri.format(DBNAME="x") == "sqlite:///{weird}.db?schema=x"


def test_kit_db_uri_applies_host_override(monkeypatch):
    monkeypatch.setenv("OEDS_DB_HOST", "db.internal")
    assert kit_db_uri({"database_uri": PACK_URI}) == (
        "postgresql://opendata:opendata@db.internal:6432/opendata?options=--search_path={DBNAME}"
    )


def test_kit_db_uri_requires_a_uri():
    with pytest.raises(KeyError):
        kit_db_uri({"schema_name": "x"})


class _Crawler(KitCrawler):
    def run(self):
        pass


def test_kit_crawler_constructs_on_sqlite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {"database_uri": "sqlite:///", "schema_name": "unit_schema"}
    with patch(
        "crawler.common.crawler_logging.RotatingFileHandler", return_value=logging.NullHandler()
    ):
        crawler = _Crawler("unit_crawler", config)

    assert crawler.crawler_name == "unit_crawler"
    assert crawler.schema_name == "unit_schema"
    assert crawler.logger.name == "unit_crawler"
    assert crawler.config["database_uri"] == "sqlite:///"
    # as before: the schema is appended to the configured URI
    assert crawler.config["db_uri"] == "sqlite:///unit_schema"
    assert str(crawler.engine.url) == "sqlite:///unit_schema"
    assert crawler.get("schema_name") == "unit_schema"
