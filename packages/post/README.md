# oeds-post-scripts

Post-run processing package of the [oeds-kit](../../README.md) workspace.
Crawler extensions, scheduling/UI and the installation live in
`packages/crawler-pack`, `packages/scheduler` and `deploy/` of the same
repository.

## Responsibility

This module should transform, validate, fill, forecast, or derive data after
crawlers have written source tables.

## Contents

- gapfilling
- price forecasting
- ENTSO-E availability map refresh
- derived SQL refresh tools
- stable `oeds-post` CLI

## CLI

```powershell
oeds-post gapfill entsoe-fms
oeds-post refresh entsoe-availability-map
oeds-post forecast day-ahead-price
oeds-post backfill entsoe-unavailability
```

Each command runs the `main()` of its module under `scripts/` in-process, in
the current working directory; further arguments are passed on (for example
`oeds-post gapfill entsoe-fms --self-test`, `oeds-post forecast day-ahead-price --help`).
`gapfill entsoe-fms` adds `--job entsoe_fms`. Set `OEDS_CRAWLER_DATA_DIR` to a
writable directory for downloaded files; installed source code can be read-only.

## Included Implementation

This package contains the current post-processing implementation:

```text
oeds_gapfill/
oeds_price_forecast/
scripts/
scripts/lib/
```

These packages and their SQL files are included in both source distributions
and wheels. The package installs without `oeds-crawler-pack`; the optional
extra `backfill` pulls it in. Database connection overrides
(`OEDS_DB_HOST`, `OEDS_DB_PORT`, `OEDS_DB_PASSWORD`) and the optional
`crawler/.env` file (or the file named by `OEDS_CRAWLER_ENV`) are handled by
`oeds_post_scripts.runtime_env`. Only `oeds-post backfill entsoe-unavailability`
imports the pack's ENTSO-E FMS crawler (extra `backfill`; the deployment image
installs all extras).
Set `OEDS_CRAWLER_CONFIG` when the operational `CRAWLER_CONFIG.yml` is not in
the working directory. The deployment sets this variable to
`/app/CRAWLER_CONFIG.yml` inside its Python containers.
For ENTSO-E backfill downloads, `OEDS_CRAWLER_DATA_DIR` selects the writable
crawler data directory; the modular deployment uses `/app/crawler/data`.

## Local Development

From the repository root:

```powershell
uv sync --all-packages
uv run oeds-post --help
```

## Test Coverage

Run the focused command tests:

```powershell
uv run --package oeds-post-scripts pytest packages/post/tests
```

Database-backed post-processing is covered by `deploy/tools/test_installation.sh`. That suite uses a real
database, deterministic gapfill/forecast cases and actual scheduler post-runs.
Live backfill needs ENTSO-E credentials and an explicitly bounded date range.

## Required Interfaces

- OEDS database schema contract
- post-run command contract
- JSON/log result format for scheduler consumption
