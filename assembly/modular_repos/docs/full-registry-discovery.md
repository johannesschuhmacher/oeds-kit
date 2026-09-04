# Full Registry Discovery

The modular scaffold now discovers crawler specs from source trees instead of
only listing the original three pilot crawlers.

## Implemented Pieces

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/discovery.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/distribution.py
modules/oeds-crawler-pack/src/oeds_crawler_pack/registry.py
tools/audit_registry.py
```

The discovery is static. It parses crawler source files with the Python AST and
does not import crawler modules. That keeps the registry build independent of
optional crawler dependencies, credentials, network access, and database
availability.

## Current Registry Sources

Configured in:

```text
docs/crawler-inventory.json
```

| Source | Path | Package path | Module prefix | Discovered class-based crawlers |
| --- | --- | --- | --- | ---: |
| `oeds-crawler-pack` | `..` | `crawler` | `crawler` | 21 |
| `oeds-core` | `sources/oeds-core` | `oeds/crawler` | `oeds.crawler` | 32 |

After priority merge:

| Metric | Count |
| --- | ---: |
| Merged crawler names | 47 |
| Active from `oeds-crawler-pack` | 21 |
| Active from `oeds-core` | 26 |

The active upstream count is lower than 32 because duplicate names such as
`smard`, `netztransparenz`, `regelleistung`, and `mastr` are intentionally
overridden by KIT versions from `oeds-crawler-pack`.

## Constructor Audit Summary

| Constructor style | Count | Meaning |
| --- | ---: | --- |
| `schema_name_config` | 27 | upstream-style `CrawlerClass(schema_name, config)` |
| `crawler_name_config` | 18 | KIT-style `CrawlerClass(crawler_name, config)` |
| `schema_name_only` | 1 | legacy upstream-style `CrawlerClass(schema_name)` |
| `unknown` | 1 | visible but not schedulable through the shared interface |

The current upstream execution special cases in the merged registry are:

| Crawler | Source | Reason |
| --- | --- | --- |
| `dwd` | `oeds-core` | requires a third constructor argument (`nuts_matrix`) and imports a missing 2021 NUTS shape file; it is not in the official registry |
| `eex` | `oeds-core` | constructor is represented as `schema_name_only`, but no supported run method is detected. |

This is not a blocker for the architecture. It means the scheduler can keep the
crawlers visible in the static inventory, but must not schedule them until an
adapter or upstream-compatible refactor defines the shared contract. The
separate `dwd_cdc` implementation remains available from `oeds-crawler-pack`.

## Important Active Overrides

These names exist in both sources but resolve to KIT because
`oeds-crawler-pack` has priority:

```text
entsog
mastr
netztransparenz
ninja
regelleistung
smard
```

This preserves the current KIT operational behavior while keeping upstream-only
crawlers available.

## Verification

Run:

```powershell
python .\modular_repos\tools\verify_modules.py
python .\modular_repos\tools\audit_registry.py
```

Current verifier result:

```text
modular repository scaffold verification passed
```
