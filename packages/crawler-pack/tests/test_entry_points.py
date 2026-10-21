from pathlib import Path

import pytest

from crawler import cli
from crawler.common.kit_base import KitCrawler

ENTRY_POINTS = cli.crawler_entry_points()
CRAWLER_MODULES = sorted(
    path.stem
    for path in Path(cli.__file__).parent.glob("*.py")
    if path.stem not in ("cli", "__init__")
)


def test_every_crawler_module_is_registered():
    assert sorted(ENTRY_POINTS) == CRAWLER_MODULES


@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_entry_point_resolves_to_kit_crawler_subclass(name):
    assert issubclass(ENTRY_POINTS[name].load(), KitCrawler)
