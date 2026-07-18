"""Print the current modular crawler registry audit as JSON."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _add_source_paths() -> None:
    scheduler_src = ROOT / "modules" / "oeds-scheduler-ui" / "src"
    for path in (scheduler_src,):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)


def main() -> None:
    _add_source_paths()

    from oeds_scheduler_ui.distribution import load_inventory, registries_from_inventory
    from oeds_scheduler_ui.factory import CrawlerFactory
    from oeds_scheduler_ui.interfaces import merge_crawler_registries

    inventory = load_inventory(ROOT / "docs" / "crawler-inventory.json")
    registries = registries_from_inventory(inventory, workspace_root=ROOT)
    merged = merge_crawler_registries(registries)
    factory = CrawlerFactory(merged)

    report = {
        "registry_counts": {
            registry.source_name: len(registry.crawlers) for registry in registries
        },
        "merged_count": len(merged),
        "summary": {},
        "crawlers": {},
    }
    constructor_styles: Counter[str] = Counter()
    unsupported_constructors: list[str] = []
    missing_run_methods: list[str] = []

    for crawler_name in factory.list_crawlers():
        audit = factory.audit(crawler_name)
        constructor_styles[audit.constructor_style] += 1
        if not audit.has_supported_constructor:
            unsupported_constructors.append(crawler_name)
        if not audit.run_methods:
            missing_run_methods.append(crawler_name)
        report["crawlers"][crawler_name] = {
            "source": audit.target.source_name,
            "module": audit.target.module,
            "attribute": audit.target.attribute,
            "constructor_style": audit.constructor_style,
            "supported_constructor": audit.has_supported_constructor,
            "run_methods": list(audit.run_methods),
            "error": audit.error,
        }

    report["summary"] = {
        "constructor_styles": dict(sorted(constructor_styles.items())),
        "unsupported_constructors": sorted(unsupported_constructors),
        "missing_run_methods": sorted(missing_run_methods),
    }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
