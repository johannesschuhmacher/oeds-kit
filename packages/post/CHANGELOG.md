# Changelog

## Unreleased

- Add `oeds_post_scripts.runtime_env` with own `resolve_database_uri` and
  `load_crawler_dotenv` helpers so post-scripts no longer import
  `crawler_core` from `oeds-crawler-pack`. `python-dotenv` is now a declared
  dependency and `OEDS_CRAWLER_ENV` can name the `.env` file to load.
- Remove the unused `scripts/lib/gapfill.py`: it carried hard-coded localhost
  credentials and its only caller was the removed SMARD gapfill.
- Remove `oeds-post gapfill smard` and `scripts/gapfill_smard.py`: the script
  filled one hard-coded week (2–9 June 2024) against hard-coded localhost
  credentials and ran uselessly after every SMARD run.
- Use ENTSO-E's harmonised r3.1 column names (`AreaMapCode`,
  `ValidityPeriodStart(UTC)`, `InstalledCapacity[MW]`, `Comment`, ...).
- Gapfill: target tables created by `to_sql` get an index on their time column
  (`CREATE INDEX IF NOT EXISTS`).
- ENTSO-E availability map: the materialized views are created `IF NOT
  EXISTS` and refreshed with `REFRESH MATERIALIZED VIEW` (one transaction per
  view) instead of being dropped and recreated every hour. After editing a
  materialized view definition, drop it once by hand. `v_outage_event_latest`
  drops closed `EndTimeSeries(UTC)` partitions before ranking versions.

## 0.1.0

- Packaged post-processing scripts, helper packages, and SQL resources.
- Declared runtime and optional price-forecast dependencies.
- Removed the installed CLI's dependency on a KIT monorepository checkout.

## 0.0.0-local

- Initial local split repository for stable `oeds-post` commands.
- Copied current KIT gapfill, forecast, refresh, and derived-data scripts.
- Added config migration from legacy `post_run_scripts` to stable commands.
- Added repo-root resolution and first direct-call support for scripts with
  safe `main()` entry points.
- Added starter GitHub Actions CI for compile and unit test checks.
