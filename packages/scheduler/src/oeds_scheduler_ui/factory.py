"""Crawler lookup through the ``oeds.crawlers`` entry points.

Every crawler package registers its crawlers under this group in its
pyproject.toml. ``oeds-crawl`` resolves names through the same group, so the
scheduler plans exactly the crawlers the command can start.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

ENTRY_POINT_GROUP = "oeds.crawlers"


def crawler_entry_points() -> dict[str, EntryPoint]:
    return {entry.name: entry for entry in entry_points(group=ENTRY_POINT_GROUP)}


def known_crawler_names() -> tuple[str, ...]:
    """Registered crawler names, sorted. No crawler module is imported."""

    return tuple(sorted(crawler_entry_points()))


def load_crawler_class(crawler_name: str) -> type:
    """Import and return the crawler class registered under ``crawler_name``."""

    entries = crawler_entry_points()
    if crawler_name not in entries:
        known = ", ".join(sorted(entries)) or "none"
        raise LookupError(
            f"no crawler '{crawler_name}' registered under {ENTRY_POINT_GROUP} "
            f"(known: {known})"
        )
    return entries[crawler_name].load()
