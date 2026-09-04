# Pilot Crawler Registry

This document records the implemented registry strategy for modular OEDS.

## Goal

Prove that the scheduler can keep KIT-enhanced crawlers ahead of upstream OEDS
crawlers while still retaining upstream-only crawlers.

## Pilot Crawler Set

| Registry name | Source | Target | Reason |
| --- | --- | --- | --- |
| `smard` | `oeds-crawler-pack` / KIT | `crawler.smard:SmardCrawler` | KIT is the current operational default and is wired to gapfill. |
| `eurostat_crawler` | `oeds-crawler-pack` / KIT | `crawler.eurostat_crawler:EurostatCrawler` | KIT-only configurable crawler. |
| `chargepoint` | OEDS core | `oeds.crawler.chargepoint:ChargepointDownloader` | Upstream-only crawler that must not be lost. |

## Implemented Pieces

### `oeds-scheduler-ui`

Implemented in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/interfaces.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/distribution.py
```

Available primitives:

- `CrawlerSpec`
- `CrawlerRegistry`
- `registry_from_spec_strings(...)`
- `merge_crawler_registries(...)`
- `load_crawler_target(...)`
- `run_crawler_instance(...)`
- `load_inventory(...)`
- `registries_from_inventory(...)`
- `CrawlerFactory`
- `ConstructorAudit`
- `ConstructorPlan`

Important behavior:

```text
Earlier registries win.
```

That means:

```text
[oeds-crawler-pack, oeds-core]
```

keeps KIT's `smard` while still adding upstream-only `chargepoint`.

### `oeds-crawler-pack`

Implemented in:

```text
modules/oeds-crawler-pack/src/oeds_crawler_pack/registry.py
```

The package currently discovers 21 bundled crawler specs, including:

```python
{
    "smard": "crawler.smard:SmardCrawler",
    "eurostat_crawler": "crawler.eurostat_crawler:EurostatCrawler",
}
```

The crawler pack resolves these specs from its own installed source tree:

```text
modules/oeds-crawler-pack/src/crawler
```

## Test Results

Current standard-library verification:

```text
modular repository scaffold verification passed
```

Module pytest suites and `tools/verify_modules.py` both cover this behavior.

## Constructor Pilot

The first constructor audit proves:

```text
smard             -> oeds-crawler-pack -> crawler_name_config
eurostat_crawler  -> oeds-crawler-pack -> crawler_name_config
chargepoint       -> oeds-core         -> schema_name_config
```

## Current Result

The scheduler loads the Crawler Pack and official OEDS registries from the
paths in `crawler-inventory.json`, merges them in declared priority, and keeps
all upstream-only crawlers available.
