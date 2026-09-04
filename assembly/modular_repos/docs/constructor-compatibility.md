# Constructor Compatibility Pilot

The first registry pilot now has a static constructor audit. The audit does not
import crawler dependencies and does not open database connections. It reads the
source files, finds the target class, detects the constructor style, and builds
a dry constructor plan.

## Implemented Module

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/factory.py
```

Main objects:

- `CrawlerFactory`
- `ConstructorAudit`
- `ConstructorPlan`
- `audit_crawler_spec(...)`
- `module_file_from_spec(...)`

Supported constructor styles:

| Style | Meaning | Used by |
| --- | --- | --- |
| `crawler_name_config` | `CrawlerClass(crawler_name, config)` | KIT crawler model |
| `schema_name_config` | `CrawlerClass(schema_name, config)` | upstream OEDS model |
| `schema_name_only` | `CrawlerClass(schema_name)` | legacy upstream crawler shape |
| `unknown` | unsupported or not statically detectable | manual review required |

## Pilot Audit Result

| Crawler | Source | Class | Constructor style | Run method | Status |
| --- | --- | --- | --- | --- | --- |
| `smard` | `oeds-crawler-pack` / KIT | `crawler.smard:SmardCrawler` | `crawler_name_config` | `run` | supported |
| `eurostat_crawler` | `oeds-crawler-pack` / KIT | `crawler.eurostat_crawler:EurostatCrawler` | `crawler_name_config` | `run` | supported |
| `chargepoint` | OEDS core | `oeds.crawler.chargepoint:ChargepointDownloader` | `schema_name_config` | `crawl_structural` | supported |

This proves the first no-loss integration pattern:

- KIT-enhanced crawlers can be preferred.
- upstream-only crawlers can stay visible.
- the scheduler can derive the constructor call style before importing heavy
  crawler modules.

## Why Static Audit First

Several crawler modules depend on optional libraries, source credentials, or
database drivers. Importing every crawler at scheduler startup is brittle.

The static audit avoids that by answering these questions from source code:

1. Does the target module file exist?
2. Does the target class exist?
3. Which base classes are declared?
4. Which run methods are present?
5. Does the constructor look like KIT or upstream OEDS?

Actual import and construction still exist through `CrawlerFactory.construct`,
but that path is expected to be used only when a job is about to run.

## Full Inventory Status

The full merged registry currently contains 47 crawler names. Constructor
compatibility is statically classified for all of them:

| Constructor style | Count | Meaning |
| --- | ---: | --- |
| `schema_name_config` | 27 | upstream-style `CrawlerClass(schema_name, config)` |
| `crawler_name_config` | 18 | KIT-style `CrawlerClass(crawler_name, config)` |
| `schema_name_only` | 1 | legacy upstream-style `CrawlerClass(schema_name)` |
| `unknown` | 1 | visible but not schedulable through the shared interface |

Two upstream legacy cases remain visible:

| Crawler | Limitation |
| --- | --- |
| `dwd` | Requires the additional constructor argument `nuts_matrix` and imports a missing 2021 NUTS shape file. It is not part of the official core registry and is not schedulable through the shared interface. |
| `eex` | Uses `schema_name_only`, but exposes no supported run method (`run`, `crawl_temporal`, or `crawl_structural`). |

The scheduler keeps both entries visible for compatibility analysis without
claiming that they can be dispatched. The supported DWD runtime path in the
modular stack is `dwd_cdc` from `oeds-crawler-pack`.

## Next Step

Use the full registry audit as input for the scheduler extraction:

1. keep constructor calls inside `CrawlerFactory`
2. let the scheduler build dry job plans from config and registry metadata
3. instantiate a crawler only when a job is dispatched
4. keep crawler implementation files outside `oeds-scheduler-ui`
