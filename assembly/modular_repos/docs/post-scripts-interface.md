# Post-Scripts Interface

`oeds-post-scripts` now provides the first stable command facade for post-run
processing.

## Goal

The scheduler should not need to know concrete script paths such as:

```text
scripts/gapfill_timeseries.py
scripts/refresh_entsoe_availability_map.py
scripts/run_price_forecast.py
```

Instead, scheduler config and UI actions should refer to stable commands:

```text
oeds-post gapfill entsoe-fms
oeds-post refresh entsoe-availability-map
oeds-post forecast day-ahead-price
```

The current implementation keeps the existing scripts as the behavior source of
truth. Where a script has a safe `main()` entry point, `run_post_command(...)`
can call it directly in-process. Scripts with import-time side effects stay on
the subprocess fallback. That avoids losing behavior while giving us a clean
boundary for deeper extraction.

## Implemented Module

```text
modules/oeds-post-scripts/src/oeds_post_scripts/commands.py
modules/oeds-post-scripts/src/oeds_post_scripts/runner.py
modules/oeds-post-scripts/src/oeds_post_scripts/cli.py
```

Main objects:

- `PostCommandSpec`
- `ResolvedPostCommand`
- `POST_COMMANDS`
- `resolve_post_command(...)`
- `command_to_legacy_argv(...)`
- `script_to_post_command(...)`
- `migrate_post_run_scripts(...)`
- `run_post_command(...)`
- `resolve_post_repo_root(...)`

## Current Stable Commands

| Stable command | Current legacy script | Notes |
| --- | --- | --- |
| `oeds-post gapfill smard` | `scripts/gapfill_smard.py` | subprocess fallback because the script executes at import time |
| `oeds-post gapfill entsoe-fms` | `scripts/gapfill_timeseries.py --job entsoe_fms` | direct-call candidate |
| `oeds-post refresh entsoe-availability-map` | `scripts/refresh_entsoe_availability_map.py` | direct-call candidate |
| `oeds-post forecast day-ahead-price` | `scripts/run_price_forecast.py` | direct-call candidate |
| `oeds-post backfill entsoe-unavailability` | `scripts/backfill_entsoe_unavailability.py` | direct-call candidate |

Additional args are forwarded to the legacy script. Example:

```powershell
oeds-post gapfill entsoe-fms --self-test
```

resolves to:

```text
python scripts/gapfill_timeseries.py --job entsoe_fms --self-test
```

The legacy-compatible script root is resolved in this order:

1. explicit `--repo-root`
2. `OEDS_POST_REPO_ROOT`
3. current working directory when it contains `scripts/`
4. the `oeds-post-scripts` module repo when it contains `scripts/`

## Migration Map

Current scheduler config can move from:

```yaml
post_run_scripts:
  - "scripts/gapfill_timeseries.py"
  - "scripts/refresh_entsoe_availability_map.py"
```

to:

```yaml
post_run_scripts:
  - "oeds-post gapfill entsoe-fms"
  - "oeds-post refresh entsoe-availability-map"
```

The scheduler runtime now supports both forms:

- `*.py` paths are still run with the current Python interpreter.
- other commands are split into process argv, so `oeds-post ...` can run when
  the package is installed.
- when `oeds_post_scripts` is importable, `oeds-post ...` commands are resolved
  through the package facade before falling back to an external process.

The package also provides a pure dict migration helper:

```python
from oeds_post_scripts.migration import migrate_post_run_scripts

migrated_config, replacements = migrate_post_run_scripts(raw_config)
```

This lets us preview or apply config migration later without changing the
operational `CRAWLER_CONFIG.yml` immediately.

The CLI exposes the same migration path:

```powershell
oeds-post --migrate-config CRAWLER_CONFIG.yml
oeds-post --migrate-config CRAWLER_CONFIG.yml --output CRAWLER_CONFIG.post.yml
```

Without `--output`, it prints a report and does not write a file.

## Current Config Migration Report

Against the current local `CRAWLER_CONFIG.yml`, the migration CLI reports these
known replacements:

| Crawler | Job | Old | New |
| --- | --- | --- | --- |
| `smard` | default | `scripts/gapfill_smard.py` | `oeds-post gapfill smard` |
| `entsoe_fms` | default | `scripts/gapfill_timeseries.py` | `oeds-post gapfill entsoe-fms` |
| `entsoe_fms` | default | `scripts/refresh_entsoe_availability_map.py` | `oeds-post refresh entsoe-availability-map` |
| `entsoe_api` | default | `scripts/run_price_forecast.py` | `oeds-post forecast day-ahead-price` |

## Verification

Run:

```powershell
python .\modular_repos\tools\verify_modules.py
```

The verifier checks:

- all canonical stable commands are registered
- legacy script paths map to stable commands
- `oeds-post gapfill entsoe-fms --self-test` resolves to the expected legacy
  argv
- config dict migration replaces known legacy script paths
- `OEDS_POST_REPO_ROOT` is honored by the runner
- scheduler post-run execution still accepts injected executors

## Next Extraction Step

The current local split has already copied the reusable internals:

```text
modules/oeds-post-scripts/oeds_gapfill/
modules/oeds-post-scripts/oeds_price_forecast/
modules/oeds-post-scripts/scripts/lib/
```

The next deeper extraction step is to move code out of the remaining script
entrypoints into importable package modules while keeping the stable
`oeds-post ...` command names unchanged.
