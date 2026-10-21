# oeds-scheduler-ui

Scheduler and crawler admin UI module for the modular OEDS stack.

The runtime expects `oeds-crawler-pack` to be installed alongside this package;
`oeds-post-scripts` is optional (see below). The deployment repository installs
all three modules and supplies the runtime configuration.

This repository is part of the modular OEDS stack. The shared crawler and
database core remains in
[open-energy-data-server](https://github.com/open-energy-data-server/open-energy-data-server),
while crawler extensions, post-processing, and installation live in
[oeds-crawler-pack](https://github.com/johannesschuhmacher/oeds-crawler-pack),
[oeds-post-scripts](https://github.com/johannesschuhmacher/oeds-post-scripts),
and [oeds-deployment](https://github.com/johannesschuhmacher/oeds-deployment).

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
- `service.py`: schedule adapter and scheduler service tick
- `application.py`: config assembly and reload boundary
- `config.py`: YAML config loading and file change signature
- `daemon.py`: stoppable loop around the scheduler application

The current KIT admin UI has also been extracted into this repo:

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
- Up to `default.max_parallel_runs` (default 3) runs execute concurrently; the
  per-job `lock_keys` (for example ENTSO-E data items) still serialise
  conflicting jobs inside the daemon.
- `run_timeout_seconds` on a crawler or job kills the process after that time
  and marks the run failed.
- Post-run commands (`post_run_scripts`) run as subprocesses after a
  successful crawler run; `*.py` paths use the current interpreter with the
  working directory on `PYTHONPATH`.

## Optional post-processing

`oeds-post-scripts` is not required. Without it, scheduled runs and the admin
UI work as usual; a post-run command whose executable is not installed (for
example `oeds-post gapfill entsoe-fms`) is skipped with a WARNING and does not
mark the run failed. The admin's Gapfill Tests page, the per-crawler gapfill and
price-forecast panels and their actions are absent until the package is installed.

## Current CLIs

The package entry point loads the modular application:

```powershell
oeds-scheduler --config CRAWLER_CONFIG.yml --daemon
```

`--once` runs one scheduler tick and waits for the started runs. `--daemon`
runs the persistent scheduler loop. `--inventory` and `--workspace-root` are
still accepted but ignored (deprecated; the deployment stops passing them in a
later release).

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

The admin UI still expects the assembled deployment workspace to provide the
current crawler package, `CRAWLER_CONFIG.yml`, `crawler/.env`, and (for the
gapfill and forecast pages) the post-script modules. That keeps crawler
implementation ownership outside this repo while preserving the current UI
behavior.

## Local Development

Install the package and run the focused tests from this repository:

```powershell
uv sync
uv run --with pytest pytest tests/test_interfaces.py
```

This checks, with a stub standing in for `oeds-crawl`:

- job expansion for `default` and named `jobs`
- exit-code mapping, per-run log files, timeouts and post-run commands
- queue locking, advisory-lock handling and bounded concurrency
- scheduler service ticks and daemon wait calculation
- application reload on config changes

The repository includes a starter GitHub Actions workflow for compile checks
and standalone scheduler-core tests. Admin UI, gapfill, database, crawler, and
Docker coverage is handled by the deployment-level full function test.

## Reproducibility Against KIT

The scheduler implementation is not a byte-for-byte copy of
`crawler_scheduler.py`; it is a modular rewrite. Reproducibility is therefore
checked by contract tests:

- same config merge behavior for `default` and `jobs`
- same `enable`, `schedule`, `post_run_scripts`, and `run_post_scripts`
  semantics
- no crawler import during planning

The admin UI has received subsequent fixes and is no longer byte-for-byte
identical to KIT. Test behavior, not source-file identity. Full admin tests
require the crawler and post-scripts modules; run them in the assembled
runtime described in the deployment repository's `docs/testing.md`.

## Future Work

- run the admin UI's specialised actions (ENTSO-E targeted/backfill, weather
  window, Eurostat range) through `oeds-crawl` as well; they are still
  in-process
- upstream contribution of generic crawler-contract improvements currently
  provided by the `oeds-crawler-pack` compatibility facade
