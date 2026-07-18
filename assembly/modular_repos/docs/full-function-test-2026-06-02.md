# Full Function Test 2026-06-02

This report records the complete local function test for the modular OEDS split.

## Scope

The test covers all locally executable functions in the current modular setup:

- module scaffold and copied-file parity
- crawler registry discovery and constructor audit
- Python syntax checks and unit tests
- post-script command registry and CLI entry points
- price forecast self-test
- scheduler planning and Admin UI import
- Docker Compose model rendering
- disposable DB initialization
- real SMARD crawler and SMARD post-run gapfill
- active configured crawler set with reduced windows
- local service stack with PostGREST, Grafana, and Crawler Admin
- Docker cleanup checks

## Environment

- Date: 2026-06-02
- Python: 3.14.4 from project `.venv`
- Docker Compose: local Docker Desktop Compose
- Test mode: `compose.yml` + `compose.modular.yml` + `compose.test.yml`
- Test data: disposable `oeds-modular-test-*` containers, networks, and volumes

## Runner

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

The runner writes the crawler registry audit to:

```text
modular_repos/.tmp/full-function-test/crawler-registry-audit.json
```

## Result

All runner steps passed.

| Area | Result | Evidence |
| --- | --- | --- |
| Module scaffold | passed | `verify_modules.py` |
| Split parity | passed | post scripts, deployment baseline, Admin UI copy |
| Crawler registry audit | passed | 47 merged crawlers |
| Deployment verifier | passed | modular Docker/Compose/test scripts |
| Python compile | passed | modular modules and tools |
| Crawler-pack tests | passed | 2 tests |
| Post-scripts tests | passed | 3 tests |
| Scheduler/UI tests | passed | 31 tests, 1 `datetime.utcnow()` warning |
| Post CLI registry | passed | 5 stable commands |
| Gapfill CLI listing | passed | ENTSO-E FMS tables listed |
| Price forecast self-test | passed | 96 forecast rows |
| Backfill CLI help | passed | command parser works |
| Legacy command print | passed | SMARD gapfill script resolved |
| Scheduler planning | passed | 47 crawlers, 5 planned jobs, 0 plan errors |
| Admin app import | passed | `OEDS Crawler Control 0.5.0` |
| Compose models | passed | modular and isolated test overlays render |
| Isolated DB smoke | passed | `readonly`, `postgis`, `linear_interpolate` |
| SMARD real crawler | passed | `8064` SMARD rows, `672` price rows |
| SMARD post-run | passed | `8064` gapfilled rows |
| Active crawler smoke | passed | active crawler set wrote rows |
| Stack smoke | passed | DB, PostGREST, Grafana, Admin UI HTTP |
| Docker leftovers | passed | no `oeds-modular-test` resources remain |

## Active Crawler Smoke Details

The active configured crawler test uses reduced windows so it can run as a
repeatable smoke test without importing full historical datasets.

| Crawler | Result | DB evidence |
| --- | --- | --- |
| `entsoe_api` | passed | `193` `entsoe_api.day_ahead_prices` rows |
| `entsoe_fms` | passed | `13223` `entsoe_fms."EnergyPrices"` rows |
| `power_system_data` | passed | `165064` `power_system_data.powersystemdata` rows |
| `weather_forecast` | passed | `1` `weather.hourly_forecast` row |

The `power_system_data` smoke also executed the EIC mapping ETL and wrote `3016`
unique mapping records during the run.

## Issue Found During This Test

The first active crawler run failed for `power_system_data` because the isolated
test runtime mounted an empty `crawler/data` directory over the image's static
mapping files.

Fix:

- `test_active_crawlers_smoke.ps1` now copies the static EIC mapping Python and
  JSON files into the ignored disposable runtime before starting the container.
- The runtime directory is removed in the script `finally` block so copied
  `.env` credentials and static files do not remain in `.tmp`.

## Not Covered As Full External Runs

The test executes every currently enabled crawler plus SMARD. It does not fully
run every optional disabled crawler. Those need separate scheduled integration
tests because they can require credentials, subscriptions, SFTP access, terms
acceptance, or large downloads.

Examples:

- `epex_spot`: SFTP account and market-data access
- `netztransparenz`: OAuth2 client credentials
- `gie_agsi_alsi`: GIE API key
- `prisma_capacity`: booked PRISMA API package
- `copernicus_cds`: CDS key and accepted dataset terms
- `eia`: EIA API key and configured API routes
- `mastr`, `ninja`, broader weather/download crawlers: potentially large pulls

These are not counted as passed by this report; they are outside the current
active local function set.
