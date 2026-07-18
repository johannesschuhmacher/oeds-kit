# Implementation Status And Next Steps

The current local state now proves the modular split through unit tests, Docker
integration tests, real crawler/database smokes, post-run processing, and stack
startup. This file keeps the historical work-package breakdown but marks the
implemented state explicitly.

## Current Verified State

- `modules/oeds-crawler-pack` is an independent local Git repository.
- `modules/oeds-scheduler-ui` is an independent local Git repository.
- `modules/oeds-post-scripts` and `modules/oeds-deployment` are initialized as
  independent local Git repositories.
- `oeds-crawler-pack` exposes pilot KIT crawler specs for:
  - `smard`
  - `eurostat_crawler`
- `oeds-scheduler-ui` can:
  - normalize KIT-style crawler config
  - represent lazy crawler targets
  - merge registries by priority
  - load a crawler class from a source path
  - build registries from `docs/crawler-inventory.json`
  - audit constructor compatibility for the full merged registry
  - build dry scheduler job plans from config without importing crawlers
  - execute planned jobs through a registry-based runtime runner
  - queue planned jobs with duplicate and lock-key protection
  - enqueue due jobs through an injectable scheduler service tick
  - assemble config, inventory, planning, runner, and service through a single
    application wrapper
  - run a persistent daemon loop around the application
  - serve the extracted KIT crawler admin UI through `oeds-crawler-admin`
- `oeds-post-scripts` can:
  - list stable post-run command names
  - map legacy script paths to `oeds-post ...` commands
  - delegate stable commands to the current legacy scripts without losing
    behavior
  - report and optionally write config migrations from legacy script paths to
    stable commands
- `oeds-post-scripts` now contains copied current implementations:
  - `oeds_gapfill/`
  - `oeds_price_forecast/`
  - `scripts/`
  - `scripts/lib/`
- `oeds-deployment` now contains copied current deployment assets:
  - `compose.yml`
  - `compose.modular.yml`
  - `docker/`
  - `playbooks/`
  - `data/provisioning/`
  - `oeds_ops/`
- `generated/CRAWLER_CONFIG.post.yml` contains a migrated config copy using
  stable `oeds-post ...` commands.
- `tools/verify_modules.py` passes with the standard library only.
- `tools/run_full_function_test.ps1` passes the complete local function test.
- Active configured crawlers with reduced windows are verified:
  - `entsoe_api`
  - `entsoe_fms`
  - `power_system_data`
  - `weather_forecast`
- The SMARD crawler and its legacy post-run gapfill path are verified against a
  disposable DB.

## Next Work Package 1: Real Source Registries

Goal: stop hard-coding pilot specs in multiple places.

Status: done for the current local split. Static source discovery finds class-based crawlers in the
current KIT tree and the local upstream OEDS core reference.

Tasks:

1. Move the pilot crawler list into one canonical inventory file. Done.
2. Let `oeds-crawler-pack` read KIT crawler specs from that file or generate
   them from the KIT source tree. Done through static discovery.
3. Add an OEDS core registry source for upstream-only crawlers. Done through
   static discovery.
4. Keep explicit priority. Done:

   ```text
   oeds-crawler-pack before oeds-core
   ```

Done when:

- `verify_modules.py` proves that `smard` resolves to KIT and `chargepoint`
  resolves to OEDS core using only the inventory/registry loader.
  Done.

## Next Work Package 2: Constructor Compatibility

Goal: instantiate crawler classes without running network or database work.

Status: done for the current merged registry. `CrawlerFactory` performs a
static constructor audit and builds dry constructor plans for KIT, upstream, and
legacy upstream constructor shapes.

Tasks:

1. Add a `CrawlerFactory` abstraction in `oeds-scheduler-ui`. Done.
2. Support both constructor shapes. Done for static audit:
   - `CrawlerClass(schema_name, config)`
   - `CrawlerClass(crawler_name, config)`
   - `CrawlerClass(schema_name)`
3. Add a dry-construction mode using a fake/minimal config. Done as
   `constructor_plan(...)`.
4. Avoid calling `run()`, `crawl_temporal()`, or DB writes during construction
   tests. Done for verifier path.

Current result:

- 47 active crawler names are visible after priority merge.
- 47 active crawler names have a supported constructor shape.
- `eex` is still marked as not schedulable because no standard run method is
  detected.

## Next Work Package 3: Extract Scheduler Planning

Goal: preserve current KIT scheduler config semantics while replacing direct
local crawler imports with registry-based planning.

Status: done for dry planning and initial runtime execution. The planner exists
in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/planner.py
```

The runtime execution layer exists in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/runtime.py
```

The scheduler service boundary exists in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/service.py
```

The application/config boundary exists in:

```text
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/application.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/config.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/daemon.py
```

Implemented:

1. Recursive default/job config merge matching current scheduler behavior.
2. Single-job and named `jobs` expansion.
3. KIT-compatible `enable`, `schedule`, `post_run_scripts`, and
   `run_post_scripts` handling.
4. Registry lookup through `CrawlerFactory`.
5. Dry `SchedulerJobPlan` objects with source name, constructor plan, normalized
   crawler config, and scheduler-owned post-run metadata.
6. Error reporting for unknown crawlers, unsupported constructors, and crawlers
   without a supported run method.
7. Registry-based runtime execution through `CrawlerJobRunner`.
8. Injectable post-run hook execution.
9. Runtime queue locking through `CrawlerJobQueue`.
10. Schedule adapter boundary and `SchedulerService.tick(...)`.
11. Full application assembly and config change detection.
12. Thin daemon loop and CLI `--daemon` mode.

Done when:

- the long-running scheduler loop consumes `SchedulerJobPlan`. Done.
- schedule strings are parsed and due jobs are enqueued. Done through
  `SchedulerService`.
- no scheduler path imports `crawler.<name>` directly during planning. Done.
- CLI supports loading the modular application and one scheduler tick. Done.
- CLI supports a persistent daemon loop. Done.
- threaded dispatch behavior can be added later if synchronous dispatch is not
  sufficient for production load.

## Next Work Package 4: Extract Scheduler Runtime

Goal: move real scheduler behavior out of the monolithic KIT repo.

Tasks:

1. Add a schedule parser boundary. Done through `CronConverterSchedule` and
   injected `ScheduleFactory`.
2. Add a long-running scheduler loop. Done through `SchedulerService`,
   `SchedulerDaemon`, and `SchedulerApplication.tick(...)`:
   - jobs expose sorted `next_run_time`
   - due jobs are enqueued
   - unblocked jobs are dispatched through `CrawlerJobQueue`
   - config reload is checked on each application tick
3. Add application assembly. Done through `SchedulerApplication`.
4. Replace direct local crawler imports with registry lookup. Done through
   `CrawlerJobRunner`.
5. Replace direct `CRAWLER_CONFIG.yml` assumptions with a config loader. Done
   through `load_scheduler_config(...)`.
6. Keep post-run script execution behind an interface. Done through the
   injected post-run executor and `oeds-post` adapter.
7. Preserve current job behavior, including `jobs`, locking, and
   `run_post_scripts`.

Done when:

- scheduler unit tests cover config parsing and registry resolution. Done in
  `verify_modules.py` and module tests.
- no shared crawler implementation file is copied into scheduler-ui. Done for
  crawler code; the copied admin UI remains a UI/runtime module artifact.

## Next Work Package 5: Extract Post-Scripts CLI

Goal: turn post-run scripts into a module with stable command names.

Status: implemented for the first local split. A stable command facade exists in:

```text
modules/oeds-post-scripts/src/oeds_post_scripts/
docs/post-scripts-interface.md
```

Tasks:

1. Add an `oeds-post` CLI skeleton. Done.
2. Add commands for:
   - `gapfill smard`
   - `gapfill entsoe-fms`
   - `refresh entsoe-availability-map`
   - `forecast day-ahead-price`
   Done. Also added `backfill entsoe-unavailability`.
3. Keep command implementation thin at first and call existing script logic.
   Done through legacy argv delegation.
4. Return structured status objects. Done through `PostCommandResult`, including
   the selected execution mode.
5. Add config migration helper for `post_run_scripts`. Done through
   `migrate_post_run_scripts(...)` and `oeds-post --migrate-config`.
6. Move implementation internals from legacy script paths into the package.
   Started by copying current implementation files into the module repo.
7. Prefer direct calls for safe `main()` scripts and keep subprocess fallback
   for scripts with import-time side effects. Done for the current safe
   candidates.

Done when:

- scheduler can represent post-run commands without knowing script file paths.
  Done for config migration and runtime command acceptance.

## Next Work Package 6: Deployment and Compatibility

Goal: wire the independent modules together without copying their internals.

Status: implemented for local development. The local split now has copied
deployment assets, a modular Compose overlay, a deployment smoke verifier, and a
deployment compatibility manifest that references all module repos.

Tasks:

1. Keep `oeds-deployment/compatibility.yml` as the compatibility source.
2. Update deployment to install components by path/ref. Done for local Docker
   builds through `compose.modular.yml` and `Dockerfile.crawler-modular`.
3. Add a smoke verifier for:
   - component paths exist
   - registry can be built
   - post-scripts CLI is visible
   - deployment manifest references known components
   Done through `tools/verify_modules.py` and
   `modules/oeds-deployment/tools/verify_deployment.py`.

Done when:

- the deployment module can describe a complete local stack from component refs.
  Done for the local split; Docker/database integration verification is covered
  by `tools/run_full_function_test.ps1`.

## Remaining Publication Work

The implementation work for the local modular split is complete enough to
prepare publication. Remaining tasks are release engineering tasks:

1. Create remotes for the four primary add-on module repositories and decide
   repository names.
2. Review and enable the prepared CI workflow in each repo; keep Docker
   integration tests as scheduled or manually triggered jobs.
3. Decide where the shared `crawler_core`/`crawler.common` compatibility layer
   should live long term.
4. Create initial commits and run
   `tools/check_publication_readiness.py --strict-git` after remotes are set.
5. Run a disposable remote-host Ansible install test before advertising the
   deployment repo as production-ready.
