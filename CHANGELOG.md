# Changelog

## Unreleased

- Run scheduled jobs as `oeds-crawl` subprocesses (exit codes 0 ok / 1 failed /
  3 skipped) instead of in-process; each run writes `logs/runs/<job>-<time>.log`
  (last 200 kept) and can be bounded by `run_timeout_seconds`.
- Discover crawlers through the `oeds.crawlers` entry points; the inventory
  JSON, the AST source scan and the constructor audit are gone. `--inventory`
  and `--workspace-root` are accepted but ignored.
- Take a PostgreSQL advisory lock per crawler before every run, in the daemon
  and in the admin UI, so the two cannot run one crawler at the same time; a
  busy job is retried on the next tick.
- Run up to `default.max_parallel_runs` (default 3) jobs concurrently.
- Admin "Run once" uses the same `oeds-crawl` subprocess path; its log no
  longer interleaves with other runs. The admin lists crawlers from the entry
  points instead of globbing `crawler/*.py`.
- Run post-run commands as subprocesses whose output goes to the run log.
- Make scheduled run outcomes visible: the daemon logs every run result, a
  failed crawler run logs CRITICAL on the crawler's own logger (which sends the
  configured alert mail), and a failing tick (for example a broken config file)
  no longer terminates the daemon.
- Treat a crawler raising `CrawlerSkipped` (detected by class name) as status
  `skipped` instead of `failed` in the scheduler runtime and the admin UI.
- Apply `OEDS_EMAIL_*` environment overrides when the scheduler daemon loads
  its config, matching the admin UI.
- Make `oeds-post-scripts` optional: the admin UI starts without it (the
  Gapfill Tests page, gapfill/price-forecast panels and actions are absent),
  and a post-run command whose executable is not installed is skipped with a
  warning instead of failing the run.
- Import `crawler.common.local_env` directly instead of the deprecated
  `crawler_core` facade.

## 0.1.0

- Discover installed crawler modules without requiring crawler sources at the
  workspace root.
- Run admin post-processing actions through the stable `oeds-post` CLI.
- Reject crawler constructors with unsupported additional required parameters
  while continuing to allow optional constructor extensions.

## 0.0.0-local

- Initial local split repository for registry-based scheduler runtime.
- Added scheduler CLI, daemon wrapper, planning, queueing, and runtime contracts.
- Extracted the current KIT crawler admin UI, templates, static assets, and
  server launcher into this module.
- Fixed legacy post-run subprocess imports by prepending the workspace CWD to
  `PYTHONPATH`.
- Fixed Admin UI repository root resolution for installed/containerized runtime
  workspaces.
- Added starter GitHub Actions CI for compile and standalone scheduler-core
  test checks.
