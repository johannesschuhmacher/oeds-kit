"""Crawler lookup, shared with ``oeds-crawl``.

Crawlers registered as ``oeds.crawlers`` entry points come first, then the
built-in crawlers of the OEDS core; the scheduler therefore plans exactly the
crawlers the command can start.
"""

from __future__ import annotations

from crawler.cli import ENTRY_POINT_GROUP, crawler_entry_points, load_crawler_class
from crawler.cli import known_crawler_names as _known_crawler_names

__all__ = ["ENTRY_POINT_GROUP", "crawler_entry_points", "known_crawler_names", "load_crawler_class"]


def known_crawler_names() -> tuple[str, ...]:
    """Registered and core crawler names, sorted."""

    return tuple(_known_crawler_names())
