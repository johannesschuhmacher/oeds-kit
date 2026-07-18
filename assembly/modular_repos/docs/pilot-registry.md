# Pilot Crawler Registry

This document records the first local implementation step for the modular OEDS
crawler strategy.

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

Current pilot specs:

```python
{
    "smard": "crawler.smard:SmardCrawler",
    "eurostat_crawler": "crawler.eurostat_crawler:EurostatCrawler",
}
```

The crawler pack points to the local KIT clone through:

```text
OEDS_KIT_SOURCE_PATH
```

or, by default:

```text
sources/oeds-kit-current
```

## Test Results

Current standard-library verification:

```text
modular repository scaffold verification passed
```

The previous pytest suites are still present in the module repositories, but
this sandbox cannot execute the user-local `uv 0.11.17` binary. The current
verification therefore uses `tools/verify_modules.py`.

## Constructor Pilot

The first constructor audit proves:

```text
smard             -> oeds-crawler-pack -> crawler_name_config
eurostat_crawler  -> oeds-crawler-pack -> crawler_name_config
chargepoint       -> oeds-core         -> schema_name_config
```

## Next Step

The next implementation step is to add actual registry loading from installed
packages or configured local source paths:

1. Load KIT crawler specs from `oeds-crawler-pack`.
2. Load OEDS core crawler specs from upstream OEDS.
3. Merge them in registry priority.
4. Instantiate one crawler through normalized config without running network or
   database work.
