# Extraction Map

This is the initial local working map for splitting OEDS-KIT into modules while
keeping upstream OEDS as the shared crawler base.

## Source of Truth

Shared crawler code should come from:

```text
sources/oeds-core/oeds/
```

KIT-specific code should be extracted from:

```text
../
```

## Target Modules

### `modules/oeds-crawler-pack`

Owns:

- KIT-only crawlers while upstream integration is pending
- improved KIT versions of crawlers that also exist upstream
- crawler registry metadata and override priority
- compatibility tests for shared crawler interfaces

Likely source paths:

```text
sources/oeds-kit-current/crawler/
```

Main interface dependency:

```text
OEDS BaseCrawler-compatible constructor and crawler registry entry points
```

### `modules/oeds-scheduler-ui`

Owns:

- scheduler service
- admin UI
- runtime config editor
- manual run controls
- run status and log inspection
- job queue and locking

Likely source paths:

```text
sources/oeds-kit-current/crawler_admin/
sources/oeds-kit-current/crawler_admin_server.py
sources/oeds-kit-current/crawler_scheduler.py
sources/oeds-kit-current/CRAWLER_CONFIG.yml
```

Current local state:

```text
modules/oeds-scheduler-ui/src/crawler_admin/
modules/oeds-scheduler-ui/src/crawler_admin_server.py
modules/oeds-scheduler-ui/src/oeds_scheduler_ui/
```

Main interface dependency:

```text
OEDS crawler registry and BaseCrawler-compatible crawler constructor
```

### `modules/oeds-post-scripts`

Owns:

- gapfilling
- forecast post-processing
- derived SQL refresh scripts
- dashboard generation scripts
- post-run CLI/API

Likely source paths:

```text
sources/oeds-kit-current/oeds_gapfill/
sources/oeds-kit-current/oeds_price_forecast/
sources/oeds-kit-current/scripts/gapfill_timeseries.py
sources/oeds-kit-current/scripts/gapfill_smard.py
sources/oeds-kit-current/scripts/backfill_entsoe_unavailability.py
sources/oeds-kit-current/scripts/refresh_entsoe_availability_map.py
sources/oeds-kit-current/scripts/run_price_forecast.py
sources/oeds-kit-current/scripts/generate_*.py
sources/oeds-kit-current/scripts/lib/
```

Current local state:

```text
modules/oeds-post-scripts/oeds_gapfill/
modules/oeds-post-scripts/oeds_price_forecast/
modules/oeds-post-scripts/scripts/
modules/oeds-post-scripts/src/oeds_post_scripts/
```

Main interface dependency:

```text
documented OEDS database schema contract and stable post-run CLI
```

### `modules/oeds-deployment`

Owns:

- Docker Compose and container build files
- Ansible playbooks
- host setup
- backup, restore, migration, rollback
- Grafana, PgAdmin, and PostgREST provisioning
- operator docs

Likely source paths:

```text
sources/oeds-kit-current/compose.yml
sources/oeds-kit-current/docker/
sources/oeds-kit-current/playbooks/
sources/oeds-kit-current/data/provisioning/
sources/oeds-kit-current/oeds_ops/
sources/oeds-kit-current/scripts/rotate_oeds_passwords.py
```

Current local state:

```text
modules/oeds-deployment/compose.yml
modules/oeds-deployment/compose.modular.yml
modules/oeds-deployment/docker/
modules/oeds-deployment/playbooks/
modules/oeds-deployment/data/provisioning/
modules/oeds-deployment/oeds_ops/
```

Main interface dependency:

```text
version-pinned component installation and database service contract
```

### Deployment Compatibility Manifest

The compatibility matrix is not a separate repository. It lives in:

```text
modules/oeds-deployment/compatibility.yml
```

It declares the compatible versions or local paths for OEDS core,
`oeds-scheduler-ui`, `oeds-post-scripts`, and the optional
`oeds-crawler-pack`. Deployment remains the complete installation entry point.

## First Implementation Milestones

1. Add an OEDS core compatibility plan for `BaseCrawler` and crawler registry.
   Done for local planning via inventory and `CrawlerFactory`.
2. Add `oeds-crawler-pack` as a temporary preservation layer for KIT crawler
   implementations. Done as registry facade.
3. Make scheduler import crawlers from OEDS core plus `oeds-crawler-pack`
   registry entries instead of local monolith paths. Done for planning/runtime
   construction.
4. Convert KIT scheduler config into normalized OEDS crawler config.
   Done in scheduler planner.
5. Extract scheduler/UI into its module repo. Done.
6. Extract post-scripts behind one `oeds-post` command. Done.
7. Extract deployment after scheduler and post-scripts are independently
   runnable. Done for local overlay.
8. Add the deployment compatibility manifest only after module boundaries are
   proven locally. Done for local staging.
