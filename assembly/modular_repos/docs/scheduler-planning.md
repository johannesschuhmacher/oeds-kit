# Scheduler Planning Interface

The first scheduler extraction step is now implemented as a dry planning layer.
It converts scheduler configuration plus the merged crawler registry into job
plans without importing crawler modules, opening database connections, or
running network code.

## Implemented Module

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/planner.py
```

Main objects:

- `CrawlerJobConfig`
- `SchedulerJobPlan`
- `SchedulerPlanIssue`
- `SchedulerPlanResult`
- `merge_job_config(...)`
- `apply_default_config(...)`
- `expand_crawler_job_configs(...)`
- `build_scheduler_job_plans(...)`

## Preserved KIT Scheduler Semantics

The planner keeps the config behavior from the current `crawler_scheduler.py`:

| Behavior | Current KIT scheduler | Modular planner |
| --- | --- | --- |
| top-level `default` config | recursively merged into each crawler | same |
| crawler-level config | inherited by named jobs | same |
| `jobs` mapping | creates one scheduler job per entry | same |
| no `jobs` mapping | creates one `default` job | same |
| `enable` | job is active only when `true` | same |
| `schedule` | kept per effective job | same |
| `run_post_scripts` | defaults to enabled unless explicitly `false` | same |
| `post_run_scripts` | remains scheduler-owned metadata | same |

The planner also accepts `enabled` as an alias when `enable` is absent. This is
for future UI clarity; `enable` remains the compatibility key.

## Registry Boundary

The scheduler now plans against `CrawlerFactory`:

```text
config + CrawlerFactory -> SchedulerPlanResult
```

That means the scheduler can answer these questions before importing crawler
code:

1. Is the crawler name known in the merged registry?
2. Which source wins after priority merge?
3. Which constructor call shape is needed?
4. Does the crawler expose a supported run method?
5. Which scheduler metadata belongs to this job?

## Job Plan Shape

Each `SchedulerJobPlan` contains:

| Field | Purpose |
| --- | --- |
| `crawler_name` | registry/config key |
| `job_name` | `default` or the named job key |
| `job_id` | stable `crawler:job` identifier |
| `source_name` | winning registry source, for example `oeds-crawler-pack` |
| `schedule` | effective schedule string |
| `run_post_scripts` | whether post-run commands should run after success |
| `post_run_scripts` | inherited scheduler-owned script list |
| `crawler_config` | normalized `OedsCrawlerConfig` for the crawler |
| `constructor_plan` | dry constructor args from `CrawlerFactory` |

The runtime scheduler should use this object as its boundary. It should import
and instantiate the crawler only when dispatching the job.

## Runtime Execution Layer

The first runtime layer is implemented in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/runtime.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/service.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/application.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/config.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/daemon.py
```

Main objects:

- `CrawlerJobRunner`
- `CrawlerRunResult`
- `PostRunCommandResult`
- `CrawlerJobQueue`
- `ScheduledCrawlerJob`
- `QueuedCrawlerJob`
- `scheduled_job_from_plan(...)`
- `lock_keys_from_plan(...)`
- `run_ready_jobs(...)`
- `SchedulerService`
- `ScheduledPlan`
- `CronConverterSchedule`
- `cron_schedule_factory(...)`
- `SchedulerApplication`
- `SchedulerApplicationSnapshot`
- `load_scheduler_config(...)`
- `SchedulerDaemon`

The runtime path is now:

```text
SchedulerJobPlan
  -> CrawlerJobRunner
  -> CrawlerFactory.construct(...)
  -> run_crawler_instance(...)
  -> optional post-run executor
```

This replaces the old direct import pattern:

```python
__import__(f"crawler.{crawler_name}")
```

with registry-based construction. The runner still supports legacy
`post_run_scripts` by default through `python <script>`, but the executor is
injected. That gives `oeds-post-scripts` a clean future integration point:

```text
post_run_scripts today -> post-run command executor tomorrow
```

The default executor now supports both legacy script paths and stable command
strings:

```text
scripts/gapfill_timeseries.py
oeds-post gapfill entsoe-fms
```

Legacy `*.py` paths are run through the current Python interpreter. Stable
commands are resolved through `oeds_post_scripts` when the package is importable
and otherwise executed as process argv.

## Queue and Locks

The new `CrawlerJobQueue` keeps the current scheduler rule that duplicate or
conflicting jobs must not run at the same time.

Default lock behavior:

| Case | Lock key |
| --- | --- |
| explicit `lock_keys` in config | those keys |
| `entsoe_fms` with `target_data_items` | one key per target data item |
| all other crawlers | `crawler:<crawler_name>` |

The `entsoe_fms` lock is intentionally conservative and does not import the
crawler class just to inspect `DATA_ITEM_TABLE_MAP`. If we need exact table-name
locks later, that mapping should become registry metadata instead of forcing a
crawler import during planning.

## Scheduler Service Tick

`SchedulerService` is the first long-running scheduler boundary, but without
owning process signals or filesystem watching yet. It does three things:

1. turns `SchedulerJobPlan.schedule` strings into schedule adapters
2. enqueues jobs whose `next_run_time` is due
3. dispatches unblocked queued jobs through `CrawlerJobRunner`

The default schedule adapter uses `cron-converter`, matching the current KIT
scheduler dependency. The adapter is injected, so tests and future deployments
can replace cron parsing without changing the runner or queue.

Current service path:

```text
SchedulerJobPlan[]
  -> SchedulerService
  -> ScheduledPlan[]
  -> CrawlerJobQueue
  -> CrawlerJobRunner
```

Still missing from the old production scheduler:

- background thread wrapper
- logging/report formatting

## Application Assembly

`SchedulerApplication` now wires the modular pieces together:

```text
YAML config file
  + crawler inventory JSON
  + workspace root
  -> registries_from_inventory(...)
  -> CrawlerFactory
  -> build_scheduler_job_plans(...)
  -> CrawlerJobRunner
  -> SchedulerService
```

The application tracks a simple file signature for the config path. Calling
`reload_if_changed(...)` rebuilds the registry, plans, runner, and service when
the config file changes. This is the stdlib replacement point for the old
`watchdog` callback.

The console entry point `oeds-scheduler` now loads this application and prints a
compact plan summary. `--once` executes one scheduler tick, and `--daemon` runs
a persistent loop around `SchedulerApplication.tick(...)`.

## Daemon Loop

`SchedulerDaemon` is intentionally thin. It does not know about crawler imports,
config format, or post-run behavior. It only:

1. calls `SchedulerApplication.tick(...)`
2. computes the next wait time from `service.next_run_time`
3. caps that wait by `poll_seconds` so config changes are noticed
4. stops when its `Event` is set

Signal handling is in the CLI, not in the scheduler core.

## Current Verification Example

The standard-library verifier now checks:

- `smard:default` resolves to `oeds-crawler-pack`
- `entsoe_fms:latest_hourly` and `entsoe_fms:revision_sweep_daily` are expanded
  from the `jobs` mapping
- job-level `target_data_items` survive the config merge
- `run_post_scripts: false` is preserved for a single job
- `chargepoint:default` resolves to upstream `oeds-core`
- unknown crawlers are skipped
- `eex` is rejected as a schedulable job because no supported run method is
  detected
- a planned runtime job constructs and runs a crawler through `CrawlerFactory`
- injected post-run hooks execute only after successful crawler runs
- queue locking blocks jobs with overlapping lock keys
- `entsoe_fms` lock keys are derived from `target_data_items`
- `SchedulerService.tick(...)` enqueues due jobs and advances their next runtime
- `SchedulerApplication` builds the full app from config + inventory
- config signature changes trigger a full reload
- `SchedulerDaemon` runs one tick and computes the next wait interval
- scheduler post-run execution accepts stable `oeds-post ...` command strings

Run:

```powershell
python .\modular_repos\tools\verify_modules.py
```

Expected result:

```text
modular repository scaffold verification passed
```

## Next Runtime Step

The next missing piece is production polish around the daemon: structured
logging/reporting, optional threaded dispatch, and config/admin integration.
