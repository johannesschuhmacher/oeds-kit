# oeds-scheduler-ui

Scheduler and crawler admin UI package of the [oeds-kit](../../README.md)
workspace.

The package depends on `oeds-crawler-pack` (`packages/crawler-pack`);
`oeds-post-scripts` (`packages/post`) is optional (see below). The deployment
in `deploy/` installs all three and supplies the runtime configuration.

## Responsibility

This module should run and operate OEDS crawlers. It owns scheduler/runtime
coordination and the operator-facing admin UI. It should not own crawler
implementation files.

## Current State

The module contains the scheduler core:

- `factory.py`: crawler lookup through the `oeds.crawlers` entry points
- `planner.py`: dry scheduler job plans from config + registered crawler names
- `runtime.py`: `oeds-crawl` subprocess runner, per-run logs, queue locking,
  bounded-concurrency dispatcher, post-run commands
- `locks.py`: cross-process crawler lock (PostgreSQL advisory lock)
- `service.py`: cron schedules (`cron-converter`) and scheduler service tick
- `application.py`: config assembly and reload boundary
- `config.py`: YAML config loading and file change signature
- `daemon.py`: stoppable loop around the scheduler application

The admin UI lives here as well:

- `crawler_admin/`: FastAPI app, templates, static files, config editor, manual
  run controls, gapfill/forecast views, and run history service
- `crawler_admin_server.py`: CLI-compatible server launcher
- `oeds-crawler-admin`: package entry point for the server launcher

Crawlers are discovered through the `oeds.crawlers` entry points that every
crawler package declares in its pyproject.toml; the scheduler never imports a
crawler module itself. The layering is `oeds < crawler-pack < scheduler < post`:
this module imports `crawler.common.*` where it needs to, nothing above it.

## How runs are executed

- A scheduled job is started as a subprocess:
  `oeds-crawl <crawler> --config CRAWLER_CONFIG.yml [--job <job>]` (the command
  comes with `oeds-crawler-pack`; `OEDS_CRAWL_COMMAND` overrides the
  executable, shell-style quoting). The child builds the effective crawler
  config itself, so a manual `oeds-crawl` and a scheduled run behave the same.
- Exit codes: `0` succeeded, `3` skipped (`CrawlerSkipped`, e.g. missing
  credentials), anything else failed. A failed run logs CRITICAL on the
  crawler's logger in the daemon with the last output line and the log path;
  the traceback is in the run log.
- Each run's stdout/stderr, including its post-run commands, goes to
  `logs/runs/<crawler>-<job>-<YYYYmmdd-HHMMSS>.log` next to the crawlers' own
  `logs/<crawler>.log` (relative to the working directory). The last 200 run
  logs are kept.
- Before a run starts, the daemon takes the PostgreSQL advisory lock
  `pg_try_advisory_lock(hashtext('oeds-crawler:<crawler>'))` on a dedicated
  connection using `default.database_uri` (with the `OEDS_DB_*` overrides).
  The admin UI takes the same lock for every manual action, so scheduler and
  admin cannot run one crawler at the same time. A job whose lock is busy is
  retried on the next tick.
- Up to `default.max_parallel_runs` (default 3) runs execute concurrently, at
  most one per crawler: a second job of a running crawler waits in the queue.
- `run_timeout_seconds` on a crawler or job kills the process after that time
  and marks the run failed.
- Post-run commands (`post_run_scripts`) run as subprocesses after a
  successful crawler run; `*.py` paths use the current interpreter with the
  working directory on `PYTHONPATH`.
- The admin's "Run once" uses the same runner for the crawler section (no
  `--job`), with the same post-run handling, `run_post_scripts` and
  `run_timeout_seconds`; its output goes to the admin's run log.
- The admin's dashboard and crawler pages show whether a crawler is running
  (its advisory lock in `pg_locks`, "unknown" without database) and the newer
  of the admin's and the scheduler's latest run. Scheduler runs are read from
  `logs/runs/` under `OEDS_ADMIN_REPO_ROOT`, which both containers mount.

## Optional post-processing

`oeds-post-scripts` is not required. Without it, scheduled runs and the admin
UI work as usual; a post-run command whose executable is not installed (for
example `oeds-post gapfill entsoe-fms`) is skipped with a WARNING and does not
mark the run failed. The admin's per-crawler gapfill and price-forecast panels
and their actions are absent until the package is installed.

## Current CLIs

The package entry point loads the modular application:

```powershell
oeds-scheduler --config CRAWLER_CONFIG.yml --daemon
```

`--once` runs one scheduler tick and waits for the started runs. `--daemon`
runs the persistent scheduler loop.

Run the admin UI:

```powershell
oeds-crawler-admin
```

Environment variables preserved from KIT:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OEDS_ADMIN_HOST` | `127.0.0.1` | bind host |
| `OEDS_ADMIN_PORT` | `3010` | bind port |
| `OEDS_ADMIN_RELOAD` | unset | enable Uvicorn reload for local development |
| `OEDS_ADMIN_STATE_DIR` | platform user data path | run history and logs |

The admin UI expects the installed crawler pack, `CRAWLER_CONFIG.yml` and
`crawler/.env` under `OEDS_ADMIN_REPO_ROOT`, and (for the gapfill and forecast
pages) the post-scripts package. Crawler implementations stay outside this
package.

## Local Development

From the repository root (the workspace installs the crawler pack and the
post-scripts, which the admin tests need):

```powershell
uv sync --all-packages
uv run --package oeds-scheduler-ui pytest packages/scheduler/tests
```

`tests/test_interfaces.py` checks, with a stub standing in for `oeds-crawl`:

- job expansion for `default` and named `jobs`
- exit-code mapping, per-run log files, timeouts and post-run commands
- queue locking, advisory-lock handling and bounded concurrency
- scheduler service ticks and daemon wait calculation
- application reload on config changes

Database, crawler and Docker coverage is handled by the deployment-level
integration test (`deploy/tests/integration.py`).

## Reproducibility Against KIT

The scheduler implementation is not a byte-for-byte copy of
`crawler_scheduler.py`; it is a modular rewrite. Reproducibility is therefore
checked by contract tests:

- same config merge behavior for `default` and `jobs`
- same `enable`, `schedule`, `post_run_scripts`, and `run_post_scripts`
  semantics
- no crawler import during planning

The admin UI has received subsequent fixes and is no longer byte-for-byte
identical to KIT. Test behavior, not source-file identity.

## Future Work

- upstream contribution of generic crawler-contract improvements currently
  provided by the `oeds-crawler-pack` compatibility facade
