# Changelog

## Unreleased

- New `oeds-crawl` command: run one crawler by hand with the config the
  scheduler would use (`oeds-crawl smard --config CRAWLER_CONFIG.yml [--job ...]`,
  `--list`). Exit codes 0 ok, 1 failed, 3 skipped. Crawlers are found through
  the `oeds.crawlers` entry points; `crawler.common.crawler_config` holds the
  default/section/job merge for both the command and the scheduler.
- BaseCrawler no longer aborts a run when its log file cannot be opened; it
  warns and continues without a file log. On intern every scheduled run had
  failed for five days because the admin container had created the log files
  as root.
- ENTSO-E FMS: read the incremental watermark once per data item instead of
  after every file; the per-file re-read dropped rows of the next file.
- ENTSO-E FMS: refresh `powersystemdata` with TRUNCATE + INSERT. Dropping the
  table failed because availability-map views depend on it, so it stopped
  updating.
- Add `crawler.common.crawler_utils.CrawlerSkipped`; crawlers without
  credentials (Copernicus, EIA, GIE, Netztransparenz, PRISMA) raise it so the
  scheduler reports the run as skipped instead of succeeded.
- GIE, Netztransparenz, PRISMA, Regelleistung and Trading Hub fail the run at
  the end when single queries, endpoints, resources, files or reports failed.
- ENTSO-E FMS: resolve every data item to the newest File Library version
  (`_r3`, `_r3.1`, `_r3.2`, ...) at run time; old versioned names in
  `target_data_items` keep working.
- ENTSO-E FMS: adopt the harmonised r3.1 column names and rename existing
  columns once in place; add columns that new extracts introduce.
- ENTSO-E FMS: add imbalance prices and volumes, redispatching,
  countertrading, congestion costs, implicit allocation net positions and
  commercial schedules.
- Normalize current ALSI LNG values with explicit units and compatible schema upgrades.
- Derive SMARD metadata coverage from stored timestamps.
- Stream MaStR ZIP members and support small, repeatable table samples.

## 0.1.0

- Bundled all current KIT crawler implementations and required data mappings.
- Bundled the temporary BaseCrawler and `crawler_core` compatibility layer.
- Removed runtime discovery from the KIT monorepository.

## 0.0.0-local

- Initial local split repository for KIT-preferred crawler registry metadata.
- Registry facade discovers KIT crawler specs from the local source tree.
- Upstream OEDS crawler specs remain available through the merged registry
  inventory.
- Added starter GitHub Actions CI and fixture-based registry tests that can run
  without a checked-out KIT workspace.
