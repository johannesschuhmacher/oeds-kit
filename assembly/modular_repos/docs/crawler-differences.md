# Crawler Differences: OEDS Core vs OEDS-KIT

This document records the current differences between the upstream OEDS crawler
set and the current OEDS-KIT crawler set. The goal is to support a modular split
without losing functionality.

## Comparison Basis

Compared local clones:

| Role | Path | Commit |
| --- | --- | --- |
| Upstream OEDS core | `sources/oeds-core` | `6d6d228f00798be3652406620959ee99080c2768` |
| OEDS-KIT current | `sources/oeds-kit-current` | `0e3ee0b8223750d9ebda3bac0793c0cbeaeb06ea` |

Crawler folders:

| Role | Folder | Python files |
| --- | --- | ---: |
| Upstream OEDS core | `sources/oeds-core/oeds/crawler` | 33 |
| OEDS-KIT current | `sources/oeds-kit-current/crawler` | 37 |

The current conclusion is:

- KIT has more operational crawler infrastructure.
- KIT has many crawler implementations that do not exist upstream.
- Several duplicate filenames hide real behavioral differences.
- Some upstream-only crawlers would be lost if we used only the KIT crawler
  folder.
- Some KIT duplicate crawlers may not be strict drop-in replacements because
  they write different tables or use different source endpoints.

Therefore the migration must use a no-loss strategy:

```text
Keep OEDS core as the center, but keep KIT crawler behavior available through
oeds-crawler-pack until each crawler has been upstreamed, preserved as an
extension, or explicitly deprecated.
```

## Runtime Model Differences

### Upstream OEDS Core

Upstream OEDS uses the package path:

```python
from oeds.base_crawler import BaseCrawler
```

Main characteristics:

- package name in `pyproject.toml`: `oeds`
- Python support: `>=3.10`
- compact config model using `db_uri`
- `BaseCrawler(schema_name, config)`
- base subclasses:
  - `ContinuousCrawler`
  - `DownloadOnceCrawler`
- common execution methods:
  - `crawl_temporal()`
  - `crawl_structural()`
  - `crawl_from_to()`
- crawler registry lives in `oeds/crawler/__init__.py`
- simpler logging setup
- metadata helper supports the basic metadata columns

### OEDS-KIT Current

OEDS-KIT uses the package path:

```python
from crawler.common.base_crawler import BaseCrawler
```

Main characteristics:

- package name in `pyproject.toml`: `open-energy-data-server`
- Python support: `>=3.14,<3.15`
- scheduler config model using `CRAWLER_CONFIG.yml`
- `BaseCrawler(crawler_name, config)`
- `schema_name`, `schedule`, `database_uri`, `email`, `logging`, and
  `post_run_scripts` are part of the operational config
- common execution method:
  - `run()`
- scheduler supports multiple jobs per crawler
- post-run scripts can be attached to crawler jobs
- logging has rotation, retention, and rate-limited SMTP alerts
- runtime helpers exist under `crawler/common/`
- metadata helper includes `concave_hull_geometry`

## BaseCrawler Differences

| Topic | Upstream OEDS | OEDS-KIT | Migration consequence |
| --- | --- | --- | --- |
| Import path | `oeds.base_crawler` | `crawler.common.base_crawler` | Need compatibility import or a shared core interface. |
| Constructor | `BaseCrawler(schema_name, config)` | `BaseCrawler(crawler_name, config)` | Scheduler must normalize both forms. |
| DB URI key | `db_uri` | `database_uri` plus `schema_name` suffix | Need config adapter supporting both keys. |
| Search path | SQLAlchemy `connect` event sets `search_path` | DB URI appends schema name after `options=--search_path=` | Need one canonical approach before upstream PR. |
| Execution model | `crawl_temporal` / `crawl_structural` | abstract `run()` | Scheduler runner must support all three. |
| Logging | basic module logging | rotating file handler, retention, SMTP rate limiting | Operational feature should stay outside core or be optional. |
| Schedule awareness | outside `BaseCrawler` | `get_next_schedule()` in `BaseCrawler` | Scheduling should move to scheduler module, not shared crawler core. |
| Metadata | basic metadata columns | adds `concave_hull_geometry` | Upstream metadata schema needs compatibility decision. |
| Helpers | `DownloadOnceCrawler`, `ContinuousCrawler`, hypertable helper | simpler abstract `BaseCrawler`, no upstream subclasses | Need adapter or staged upstream refactor. |

## Inventory Categories

### Present Only in Upstream OEDS

These crawler files exist upstream but not in the current KIT crawler folder.
They should remain available through OEDS core until explicitly replaced.

| File | Main class | Entry model | Initial action |
| --- | --- | --- | --- |
| `chargepoint.py` | `ChargepointDownloader` | `crawl_structural` | Keep via OEDS core. |
| `dwd.py` | `DWDCrawler` | `crawl_from_to` | Keep via OEDS core; compare with KIT `dwd_cdc`, `open_meteo`, and `weather_forecast`. |
| `e2watch.py` | `E2WatchCrawler` | `crawl_structural`, `crawl_from_to` | Keep via OEDS core unless obsolete. |
| `ecmwf_crawler.py` | `EcmwfCrawler` | `crawl_from_to` | Compare with KIT `ecmwf.py`, `copernicus_cds.py`, and weather crawlers. |
| `eon_grid_fees.py` | `EonGridFeeCrawler` | `crawl_structural` | Keep via OEDS core unless a KIT replacement exists later. |
| `fernwaerme_preisuebersicht.py` | `FWCrawler` | `crawl_structural` | Keep via OEDS core. |
| `gie_crawler.py` | `GieCrawler` | `crawl_from_to` | Compare with KIT `gie_agsi_alsi.py`. |
| `instrat_pl.py` | `InstratPlCrawler` | `crawl_from_to` | Keep via OEDS core unless deprecated. |
| `jao_crawler.py` | `JaoCrawler` | `crawl_from_to` | Keep via OEDS core; no KIT equivalent found. |
| `jrc_idees.py` | `JrcIdeesCrawler` | `crawl_structural` | Keep via OEDS core. |
| `nuts_mapper.py` | `NutsCrawler` | `crawl_structural` | Keep via OEDS core or move NUTS base data into shared core. |
| `oep.py` | `OepCrawler` | `crawl_structural` | Keep via OEDS core. |
| `opec.py` | `OpecDownloader` | `crawl_structural` | Keep via OEDS core. |
| `refit.py` | `RefitCrawler` | `crawl_structural` | Keep via OEDS core. |
| `synpro.py` | `SynproLoadProfileCrawler` | `crawl_structural` | Keep via OEDS core. |

### Present Only in OEDS-KIT

These crawler files exist in KIT but not upstream. They must be preserved in
`oeds-crawler-pack` unless and until they are upstreamed.

| File | Main class | Entry model | Key config/env signals | Initial action |
| --- | --- | --- | --- | --- |
| `axxteq.py` | no class detected | `main` | none detected | Review manually; likely legacy/manual crawler. |
| `copernicus_cds.py` | `CopernicusCdsCrawler` | `run` | `dataset`, `request`, `storage_dir`, `target_suffix` | Preserve in crawler pack; extension candidate. |
| `dwd_cdc.py` | `DwdCdcCrawler` | `run` | `months`, `variables`, `user_agent` | Preserve; possible upstream candidate. |
| `ecmwf.py` | no class detected | `main` | none detected | Review relation to upstream `ecmwf_crawler.py`. |
| `eia.py` | `EiaCrawler` | `run` | `lookback_days`, `requests`, `page_size`, `user_agent` | Preserve as extension crawler. |
| `energy_forecast_crawler.py` | `EnergyForecastCrawler` | `run` | `ENERGY_FORECAST_TOKEN` | Preserve as extension crawler. |
| `enet.py` | no class detected | `main` | none detected | Review manually. |
| `entsoe_api.py` | `EntsoeApiCrawler` | `run` | `ENTSOE_API_KEY`, `lookback_days`, `lookahead_days`, `include_*` | Preserve; high-priority upstream or extension candidate. |
| `entsoe_fms.py` | `EntsoeFMSCrawler` | `run` | `ENTSOE_USERNAME`, `ENTSOE_PASSWORD`, `target_data_items`, `fms_package_*` | Preserve; high-priority extension crawler. |
| `epex_spot.py` | `EpexSpotCrawler` | `run` | SFTP env vars, `target_datasets`, `include_*` | Preserve as credentialed extension crawler. |
| `eurostat_crawler.py` | `EurostatCrawler` | `run` | `dataset_id`, `start_year`, `end_year`, `table_name` | Preserve; likely upstream candidate. |
| `gie_agsi_alsi.py` | `GieAgsiAlsiCrawler` | `run` | `lookback_days`, `queries`, `page_size` | Preserve; compare with upstream `gie_crawler.py`. |
| `open_meteo.py` | `OpenMeteoCrawler` | `run` | `forecast_days`, `past_days`, `locations`, `hourly_variables` | Preserve; possible upstream candidate. |
| `osm_power.py` | `OsmPowerCrawler` | `run` | `bbox`, `power_tags`, `max_elements`, `overpass_url` | Preserve as extension/upstream candidate. |
| `power_system_data.py` | `PowerSystemDataCrawler` | `run` | `schema_name` | Preserve; extension candidate. |
| `prisma_capacity.py` | `PrismaCapacityCrawler` | `run` | `resources`, `user_agent` | Preserve as credentialed extension crawler. |
| `scigrid.py` | no class detected | `main` | none detected | Review manually; likely legacy/manual crawler. |
| `tradinghub.py` | `TradingHubCrawler` | `run` | `lookback_days`, `reports`, `user_agent` | Preserve as extension/upstream candidate. |
| `weather_forecast.py` | `WeatherForecastCrawler` | `run` | `forecast_hours`, `past_hours`, `locations` | Preserve; high-priority operational crawler. |

## Duplicate Filename Comparison

These files exist in both repositories. They should not be blindly replaced.

| File | Upstream model | KIT model | Diff size | Current interpretation | Preferred migration stance |
| --- | --- | --- | --- | --- | --- |
| `eex.py` | `BaseCrawler`, `main` | `BaseCrawler`, `main` | 1 insertion, 1 deletion | Mostly import-path adaptation. | Low risk; keep one implementation after import compatibility. |
| `entsoe_crawler.py` | `ContinuousCrawler`, `crawl_temporal` | `BaseCrawler`, `main` | 224 insertions, 175 deletions | Legacy ENTSO-E crawler differs, but KIT also has newer `entsoe_api` and `entsoe_fms`. | Preserve both until ENTSO-E strategy is decided. |
| `entsog.py` | `ContinuousCrawler`, `crawl_temporal` | `BaseCrawler`, `run` | 226 insertions, 236 deletions | KIT adds scheduler-style run, chunking, pauses, configurable start date. | Prefer KIT operational version, but compare output tables. |
| `eview.py` | `ContinuousCrawler` | `BaseCrawler` | 53 insertions, 71 deletions | Mostly runtime-interface change. | Low/medium risk; verify output schema. |
| `frequency.py` | `DownloadOnceCrawler` | `BaseCrawler` | 37 insertions, 38 deletions | Mostly runtime-interface change. | Low risk if output is unchanged. |
| `iwugebaeudetypen.py` | `DownloadOnceCrawler` | `BaseCrawler` | 147 insertions, 150 deletions | Significant rewrite or interface adaptation. | Verify source/output before choosing. |
| `ladesaeulenregister.py` | `DownloadOnceCrawler` | helper functions, `main` | 29 insertions, 32 deletions | KIT no class detected; likely manual/schema helper adaptation. | Keep upstream class unless KIT behavior is required. |
| `londondatastore.py` | `DownloadOnceCrawler` | helper functions, `main` | 40 insertions, 48 deletions | KIT no class detected; likely manual/schema helper adaptation. | Keep upstream class unless KIT behavior is required. |
| `mastr.py` | `DownloadOnceCrawler`, `open_mastr` | `BaseCrawler`, `run` | 131 insertions, 27 deletions | KIT directly downloads Marktstammdatenregister export; upstream delegates to `open_mastr`. | Prefer KIT if it is the current working path; validate completeness. |
| `netztransparenz.py` | `ContinuousCrawler`, `netztransparenz` client package | `BaseCrawler`, `run`, direct API | 457 insertions, 270 deletions | KIT adds direct endpoint framework, raw/normalized tables, endpoint run tracking, OAuth/env helper flow. | Prefer KIT operational version. |
| `ninja.py` | `DownloadOnceCrawler` | `BaseCrawler`, `run` | 91 insertions, 75 deletions | KIT makes data files configurable via scheduler config. | Prefer KIT if current config-driven behavior is required. |
| `nrw_kwp_waermedichte.py` | `DownloadOnceCrawler` | `BaseCrawler` | 47 insertions, 42 deletions | Runtime adaptation; likely similar source. | Verify output schema. |
| `opsd.py` | `DownloadOnceCrawler` | helper functions, `main` | 37 insertions, 75 deletions | KIT no class detected; likely reduced/manual version. | Keep upstream class unless KIT behavior is required. |
| `regelleistung.py` | `ContinuousCrawler`, fixed URL/table map | `BaseCrawler`, `run`, API v2 file discovery | 296 insertions, 649 deletions | KIT uses newer API/file discovery and normalized raw/numeric tables; upstream creates many fixed wide tables. | Prefer KIT for operations, but keep upstream table contract if dashboards depend on it. |
| `smard.py` | `ContinuousCrawler`, broad SMARD module API | `BaseCrawler`, `run`, chart data/upsert | 220 insertions, 217 deletions | Both are substantial but not equivalent. Upstream covers more SMARD modules; KIT has robust upsert and scheduler integration for selected generation/price data. | Preserve both until table/output mapping is explicit. |
| `vea_industrial_load_profiles.py` | `DownloadOnceCrawler` | `BaseCrawler` | 97 insertions, 58 deletions | Runtime adaptation plus possible parsing changes. | Verify output schema. |
| `windmodel.py` | `DownloadOnceCrawler` | helper functions, `main` | 18 insertions, 28 deletions | KIT no class detected; likely manual/schema helper adaptation. | Keep upstream class unless KIT behavior is required. |

## High-Impact Difference Notes

### `smard.py`

Upstream:

- Uses SMARD NIP download manager endpoint.
- Uses `ContinuousCrawler`.
- Defines module groups such as generation, market, power flow, allocation,
  forecast day-ahead, consumption, and frequency reserve.
- Writes separate tables per module group with hourly resolution.
- Temporal start is 2015.

KIT:

- Uses SMARD chart data endpoint.
- Uses scheduler `run()`.
- Focuses on selected German generation/consumption commodities and price.
- Writes `smard` and `prices` tables.
- Uses PostgreSQL upsert with `ON CONFLICT`.
- Has configurable `default_start_date`.
- Has weekly boundary logic to refill recent gaps.
- Is wired to post-run `scripts/gapfill_smard.py`.

Conclusion:

The two implementations are not strict replacements. KIT is more operationally
integrated, but upstream appears to cover broader SMARD module groups. For now,
the deployment stack should keep KIT `smard` as the scheduler default and keep
upstream `smard` available under a distinct registry name or through OEDS core
until outputs are mapped.

### `netztransparenz.py`

Upstream:

- Uses the external `netztransparenz` Python client.
- Expects `ipnt_client_id` and `ipnt_client_secret` in config.
- Implements a set of source-specific methods for forecasts, extrapolations,
  redispatch, NRV/RZ balances, and reserve activation.
- Uses `ContinuousCrawler`.

KIT:

- Uses direct API calls and OAuth token handling.
- Supports configurable endpoint lists.
- Writes operational metadata:
  - `endpoint_runs`
  - `raw_rows`
  - `normalized_values`
  - `latest_values` view
  - `endpoint_summary` view
- Uses shared HTTP/session utilities and access status helpers.
- Reads credentials from config or environment.

Conclusion:

KIT is the preferred operational implementation. Before upstreaming, decide
whether upstream should adopt KIT's normalized/raw schema or keep the older
source-specific table names for compatibility.

### `regelleistung.py`

Upstream:

- Uses fixed download URL templates and many table-specific transformation
  functions.
- Writes wide domain-specific tables such as FCR/aFRR/mFRR demand and result
  tables.
- Uses `ContinuousCrawler`.

KIT:

- Uses the regelleistung API v2 file discovery endpoint.
- Configures product types, markets, file types, page size, lookback window,
  and max files per run.
- Writes:
  - `tender_files`
  - `file_rows`
  - `numeric_values`
  - summary/latest views
- Normalizes workbook data into raw JSON rows and numeric long-format values.

Conclusion:

KIT is likely more robust for ongoing operations, but the output schema is not
compatible with upstream's wide tables. If old dashboards depend on upstream
table names, add compatibility views or keep the upstream crawler available.

### `mastr.py`

Upstream:

- Uses `open_mastr`.
- Very small wrapper around the external package.
- Uses `DownloadOnceCrawler`.

KIT:

- Downloads from the Marktstammdatenregister full export URL directly.
- Exposes `base_download_url` in config.
- Writes downloaded tables itself.
- Uses scheduler `run()`.

Conclusion:

KIT gives more local control over the download/write path. Validate whether it
covers all upstream `open_mastr` outputs before replacing upstream in core.

### `entsog.py`

Upstream:

- Uses `ContinuousCrawler`.
- Has reference and operational data logic.
- Simpler operational config.

KIT:

- Uses scheduler `run()`.
- Adds `default_start_date`, `chunk_days`, and `request_pause_seconds`.
- Separates replacement of reference tables from append of temporal tables.
- Updates metadata with temporal bounds from the configured run.

Conclusion:

KIT is the better operational default if output table names remain acceptable.
Run a table-level comparison before upstreaming.

### ENTSO-E Split

Upstream has one main `entsoe_crawler.py`.

KIT has:

- `entsoe_crawler.py` legacy/shared variant
- `entsoe_api.py` for selected Transparency Platform API time series
- `entsoe_fms.py` for File Library/FMS package refresh workflows

KIT also connects these workflows to:

- gapfilling
- availability map refresh
- price forecasting
- multiple scheduler jobs

Conclusion:

Do not collapse these back into one upstream-style crawler. Treat KIT's ENTSO-E
stack as a higher-capability crawler family. Preserve `entsoe_api` and
`entsoe_fms` as first-class extension crawlers, then decide which parts are
general enough for upstream OEDS.

## Config Differences

Upstream crawler config is mostly a flat file with source credentials and
`db_uri`.

KIT scheduler config includes:

- `enable`
- `schema_name`
- `description`
- `schedule`
- `post_run_scripts`
- `jobs`
- crawler-specific runtime windows
- crawler-specific target datasets
- email settings
- logging settings
- `database_uri`

Crawler examples in KIT:

| Crawler | KIT-specific config examples |
| --- | --- |
| `entsoe_fms` | `jobs`, `target_data_items`, `fms_package_window_months`, `fms_package_write_mode`, `gapfill` |
| `entsoe_api` | `lookback_days`, `lookahead_days`, `include_day_ahead_prices`, `include_exaa_prices`, `include_load_forecast` |
| `weather_forecast` | `forecast_hours`, `past_hours`, `locations` |
| `regelleistung` | `lookback_days`, `max_files_per_run`, `download_files`, `markets`, `product_types` |
| `epex_spot` | `start_date`, `update_interval_days`, `include_continuous_*`, SFTP settings |
| `netztransparenz` | `lookback_days`, `request_pause_seconds`, endpoint settings |

Migration implication:

The modular scheduler must preserve the KIT config shape and translate only the
crawler-relevant subset into the shared crawler constructor.

## Recommended Registry Policy

Use explicit crawler source priority:

1. Deployment override.
2. `oeds-crawler-pack` KIT-enhanced crawler.
3. Upstream OEDS core crawler.

Initial registry examples:

| Registry name | Preferred source now | Reason |
| --- | --- | --- |
| `smard` | `oeds-crawler-pack` | KIT is wired to current gapfill and scheduler behavior. |
| `smard_upstream` | OEDS core | Keep broad upstream SMARD module implementation available. |
| `netztransparenz` | `oeds-crawler-pack` | KIT has direct API/raw-normalized operational model. |
| `regelleistung` | `oeds-crawler-pack` | KIT has API v2 discovery and normalized long-format outputs. |
| `regelleistung_upstream` | OEDS core | Keep wide-table output available if dashboards need it. |
| `entsoe_api` | `oeds-crawler-pack` | KIT-only high-value crawler. |
| `entsoe_fms` | `oeds-crawler-pack` | KIT-only high-value crawler. |
| `weather_forecast` | `oeds-crawler-pack` | KIT-only operational weather crawler. |
| `chargepoint` | OEDS core | Upstream-only crawler. |
| `jao` | OEDS core | Upstream-only crawler. |

## No-Loss Checklist Per Crawler

Before replacing or moving a crawler, record:

1. Source endpoint and auth model.
2. Constructor signature.
3. Required config keys.
4. Environment variable names.
5. Main run method.
6. Tables written.
7. Primary keys and upsert/delete behavior.
8. Metadata update behavior.
9. Post-run scripts or downstream dashboards.
10. Existing tests.
11. Proposed owner:
    - OEDS core
    - `oeds-crawler-pack`
    - deprecated/archive

## Immediate Next Steps

1. Create a machine-readable crawler inventory file from this document.
2. Add registry entries for a three-crawler pilot:
   - `smard` from KIT
   - `eurostat_crawler` from KIT
   - `chargepoint` from upstream OEDS
3. Add import/construction tests for all three.
4. Add table-output notes for `smard`, `netztransparenz`, `regelleistung`,
   `mastr`, `entsog`, `entsoe_api`, and `entsoe_fms`.
5. Decide whether duplicate crawler names should expose upstream variants with
   suffix names such as `_upstream` during the transition.
