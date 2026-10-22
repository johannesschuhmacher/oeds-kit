# oeds-crawler-pack

Installable package for the KIT crawler extensions while upstream OEDS
remains the base project.

This package is part of the [oeds-kit](../../README.md) workspace. The shared
crawler and database core remains in
[open-energy-data-server](https://github.com/open-energy-data-server/open-energy-data-server)
(installed as the `oeds` dependency); scheduling/UI, post-processing and the
deployment live in `packages/scheduler`, `packages/post` and `deploy/` of the
same repository.

## Responsibility

This module contains the KIT-enhanced crawler implementations and their shared
base class `crawler.common.kit_base.KitCrawler`. It does not contain the
scheduler, post-run scripts, or deployment.

The generic parts of `KitCrawler` (per-crawler logging, database URI
handling) are intended for an upstream contribution to OEDS. Until that
contribution is accepted, they are kept here.

This package exists to prevent functionality loss while improved KIT crawlers
are prepared for upstream OEDS or kept as extension crawlers.

## Current Behavior

- ships all current KIT crawler implementations as importable `crawler.*`
- registers its crawlers as `oeds.crawlers` entry points such as
  `crawler.smard:SmardCrawler` (`oeds-crawl --list` shows them)
- `oeds-crawl` (and therefore the scheduler) also runs the built-in crawlers of
  `oeds-core` (`oeds.crawler`, installed with the extra `oeds[crawlers]`); a pack
  crawler replaces a core crawler of the same name (`smard`, `mastr`, `entsog`,
  `netztransparenz`, `ninja`). Core crawlers get the pack's log file and alert
  mail, and their API keys (`entsoe_api_key`, `gie_api_key`, `ipnt_client_id`,
  `ipnt_client_secret`, `jao_api_key`) from the crawler `.env` unless the config
  section sets them

The registry priority is:

```text
oeds-crawler-pack before oeds-core
```

## Base class

`crawler.common.kit_base.KitCrawler` is upstream's `oeds.base_crawler.BaseCrawler`
(engine, `search_path`, `create_schema`) plus the pack's additions: a rotating
file log `logs/<crawler>.log` and rate-limited critical-error mails on the
logger named after the crawler (`crawler.common.crawler_logging`), dotted
config access `self.get("a.b")`, and `set_metadata` with
`concave_hull_geometry`. Constructors take `(crawler_name, config)`; the
`database_uri` config key (ending in `?options=--search_path=`) stays valid,
`kit_db_uri` turns it into the `{DBNAME}` form upstream expects.
Crawlers subclass `KitCrawler` directly; there is no other base-class import
path. Other modules use `crawler.common.local_env` (dotenv, email overrides)
and `crawler.common.runtime_env.resolve_database_uri`.

## Local Development

From the repository root (one `uv.lock` for the whole workspace):

```powershell
uv sync --all-packages
uv run --package oeds-crawler-pack pytest packages/crawler-pack/tests
uv run oeds-crawl --list
```

## Live Validation

Run credentialed source checks through `deploy/tools/test_live_crawlers.sh`,
not through unit tests. It uses isolated databases and can exercise both KIT
and upstream implementations. See the
[live crawler report](../../deploy/docs/crawler-live-tests.md)
for commands, measured results and known failures. Registry availability does
not mean that every remote source is operational.

The package includes the NetCDF backend for Copernicus statistics. EPEX trade
archives use the existing `database_batch_size` setting for CSV processing as
well as database writes. Energy Forecast CSV history follows
`OEDS_CRAWLER_DATA_DIR` (default: `crawler/data`).

MaStR reads the remote ZIP with HTTP range requests. For a small test, set
`tables: [EinheitenWind, Katalogkategorien, Katalogwerte]` and
`max_rows_per_table: 100` in that crawler's configuration. Omit both settings
for the full import. The bounded import is a sample, not a complete register;
repeating it updates matching primary keys without adding duplicates.

GIE keeps AGSI storage columns separate from ALSI LNG columns. The explicit
`lng_*` fields distinguish GWh, thousand cubic metres and GWh/day; raw source
payloads remain available. Existing inventory tables and the latest-inventory
view are upgraded in place. SMARD metadata records actual stored date bounds.

## Policy

No crawler should be removed from the deployable crawler set until it has one of
these documented outcomes:

- merged into upstream OEDS
- kept here as an extension crawler
- replaced by a verified equivalent
- explicitly deprecated

## Out Of Scope

- scheduler UI
- deployment playbooks
- post-run gapfill or forecast pipelines
