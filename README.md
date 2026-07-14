# oeds-post-scripts

Post-run processing module for the modular OEDS stack.

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

These commands currently delegate to the existing legacy scripts instead of
copying their internals. That preserves behavior while giving the scheduler a
stable command vocabulary.

Command execution resolves the legacy-compatible script root in this order:

1. explicit `--repo-root`
2. `OEDS_POST_REPO_ROOT`
3. current working directory when it contains `scripts/`
4. this module repository when it contains `scripts/`

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

## Source Candidates

```text
../../sources/oeds-kit-current/oeds_gapfill/
../../sources/oeds-kit-current/oeds_price_forecast/
../../sources/oeds-kit-current/scripts/
../../sources/oeds-kit-current/scripts/lib/
```

## Current Copied Implementation

This module repository now contains local copies of the current KIT
post-processing implementation:

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
This keeps current behavior intact while making the repository independently
developable.

Current direct-call candidates:

| Stable command | Direct mode |
| --- | --- |
| `oeds-post gapfill entsoe-fms` | yes |
| `oeds-post refresh entsoe-availability-map` | yes |
| `oeds-post forecast day-ahead-price` | yes |
| `oeds-post backfill entsoe-unavailability` | yes |
| `oeds-post gapfill smard` | no, script has import-time execution |

## Reproducibility Against KIT

The copied implementation is checked byte-for-byte against the current KIT
checkout:

```powershell
python .\modular_repos\tools\verify_split_parity.py
```

If this check passes, the copied post-processing files are identical to KIT.
They should produce the same results under the same Python environment,
database contents, credentials, and external source availability.

## Local Development

List stable commands:

```powershell
$env:PYTHONPATH=".\modular_repos\modules\oeds-post-scripts\src"
python -m oeds_post_scripts.cli --list
```

Preview config migration:

```powershell
$env:PYTHONPATH=".\modular_repos\modules\oeds-post-scripts\src"
python -m oeds_post_scripts.cli --migrate-config .\CRAWLER_CONFIG.yml
```

Preview the command that would run against the module-local implementation:

```powershell
$env:PYTHONPATH=".\modular_repos\modules\oeds-post-scripts\src"
python -m oeds_post_scripts.cli --repo-root .\modular_repos\modules\oeds-post-scripts --print-command gapfill entsoe-fms
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
