# SPDX-FileCopyrightText: Florian Maurer, Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compatibility module: the pack's crawlers and ``crawler_core`` still import
``BaseCrawler`` from here. The implementation is ``crawler.common.kit_base``."""

from sqlalchemy import text

from crawler.common.kit_base import KitCrawler as BaseCrawler
from crawler.common.kit_base import set_metadata_with_geometry as set_metadata_only

__all__ = ["BaseCrawler", "create_schema_only", "set_metadata_only"]


def create_schema_only(engine, schema_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
