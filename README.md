# oeds-post-scripts

Post-run processing module for the modular OEDS stack.

This repository is part of the modular OEDS stack. The shared crawler and
database core remains in
[open-energy-data-server](https://github.com/open-energy-data-server/open-energy-data-server),
while crawler extensions, scheduling/UI, and installation live in
[oeds-crawler-pack](https://github.com/johannesschuhmacher/oeds-crawler-pack),
[oeds-scheduler-ui](https://github.com/johannesschuhmacher/oeds-scheduler-ui),
and [oeds-deployment](https://github.com/johannesschuhmacher/oeds-deployment).

## Responsibility

This module should transform, validate, fill, forecast, or derive data after
crawlers have written source tables.

## Contents

- gapfilling
- price forecasting
- ENTSO-E availability map refresh
- dashboard generation
- derived SQL refresh tools
- stable `oeds-post` CLI

## Current CLI Facade

Implemented command facade:

```powershell
oeds-post gapfill smard
oeds-post gapfill entsoe-fms
oeds-post refresh entsoe-availability-map
oeds-post forecast day-ahead-price
oeds-post backfill entsoe-unavailability
```

These commands delegate to the included legacy-compatible modules. This
preserves behavior while giving the scheduler a stable command vocabulary.

Command execution resolves the legacy-compatible script root in this order:

1. explicit `--repo-root`
2. `OEDS_POST_REPO_ROOT`
3. current working directory when it contains `scripts/`
4. the installed module location

The subprocess runs with the resolved root as its working directory. That keeps
legacy relative imports and `scripts/lib` behavior stable even when `oeds-post`
is called from the scheduler module or a deployment checkout.

Useful migration helper:

```powershell
oeds-post --from-script scripts/gapfill_timeseries.py
oeds-post --list
oeds-post --migrate-config CRAWLER_CONFIG.yml
oeds-post --migrate-config CRAWLER_CONFIG.yml --output CRAWLER_CONFIG.post.yml
```

Current scheduler config can migrate from:

```yaml
post_run_scripts:
  - "scripts/gapfill_timeseries.py"
```

to:

```yaml
post_run_scripts:
  - "oeds-post gapfill entsoe-fms"
```

For automated migration previews, use:

```python
from oeds_post_scripts.migration import migrate_post_run_scripts
```

## Included Implementation

This module repository contains the current post-processing implementation:

```text
oeds_gapfill/
oeds_price_forecast/
scripts/
scripts/lib/
```

The stable `oeds-post` commands still keep the legacy-compatible paths as their
behavioral source of truth. Scripts with a safe `main()` entry point can be
called directly in-process; scripts with import-time side effects, such as the
current `gapfill_smard.py`, continue to run through the subprocess fallback.
These packages and their SQL files are included in both source distributions
and wheels. The repository can therefore be installed independently of the KIT
monorepository. The ENTSO-E backfill command additionally requires
`oeds-crawler-pack`, which the deployment installs alongside this module.
Set `OEDS_CRAWLER_CONFIG` when the operational `CRAWLER_CONFIG.yml` is not in
the post-scripts repository root. The modular deployment sets this variable to
`/app/CRAWLER_CONFIG.yml` inside its Python containers.

Current direct-call candidates:

| Stable command | Direct mode |
| --- | --- |
| `oeds-post gapfill entsoe-fms` | yes |
| `oeds-post refresh entsoe-availability-map` | yes |
| `oeds-post forecast day-ahead-price` | yes |
| `oeds-post backfill entsoe-unavailability` | yes |
| `oeds-post gapfill smard` | no, script has import-time execution |

## Local Development

List stable commands:

```powershell
uv sync
uv run oeds-post --list
```

Preview config migration:

```powershell
uv run oeds-post --migrate-config .\CRAWLER_CONFIG.yml
```

Preview the command that would run against the module-local implementation:

```powershell
uv run oeds-post --print-command gapfill entsoe-fms
```

## Test Coverage

The full local function test covers the command registry, gapfill table listing,
price forecast self-test, backfill CLI parsing, and the SMARD post-run path:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

The repository includes a starter GitHub Actions workflow for compile and unit
test checks. Database-backed post-processing remains covered by the
deployment-level full function test.

## Required Interfaces

- OEDS database schema contract
- post-run command contract
- JSON/log result format for scheduler consumption
