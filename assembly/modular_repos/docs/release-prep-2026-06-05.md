# Release Prep 2026-06-05

This note records the current publication preparation state after the latest
full local verification.

## Recommended Remote Names

Use short `oeds-*` names. They are easy to read, keep the upstream OEDS center
visible, and leave room for additional add-on modules later.

| Purpose | Recommended remote name | Alternative |
| --- | --- | --- |
| KIT/preferred crawler registry and extension crawler pack | `oeds-crawler-pack` | `open-energy-data-server-crawler-pack` |
| Scheduler runtime plus Admin UI | `oeds-scheduler-ui` | `open-energy-data-server-scheduler-ui` |
| Stable post-processing CLI and scripts | `oeds-post-scripts` | `open-energy-data-server-post-scripts` |
| Docker, Compose, Ansible, ops tooling, compatibility manifest | `oeds-deployment` | `open-energy-data-server-deployment` |

Recommended first tags:

```text
v0.0.0-rc.1
```

Keep `oeds-deployment` as the public installation entry point. It owns the
compatibility manifest that pins compatible tags of OEDS core and the add-on
repos.

## Internal VM Test

Detailed VM test instructions:

```text
docs/intern-test-vm-test-plan.md
```

Configured host:

```text
inventory host: oeds-intern-test
ansible_host: iip-vm-oeds-intern-test.iip.kit.edu
ansible_user: oeds
```

Current result:

- TCP port 22 is reachable.
- Ansible is available in WSL.
- SSH login without interactive password does not work for `oeds`.
- SSH login without interactive password also does not work for `js2644`.
- `ansible -i inventory.yml oeds -m ping` fails with SSH authentication denied.
- No remote changes were made.

Next requirement: provide a working SSH key, configure `ansible_user`, or run
the VM test from a control node that already has access.

## Fresh Checkout Simulation

Because the module remotes and initial commits do not exist yet, a true
`git clone` fresh checkout is not possible. A clean source export was created
under the local temp directory without `.git`, `.env`, runtime folders, Docker
data, caches, or virtual environments.

Checks that passed in the clean export:

```powershell
python -B .\modular_repos\tools\check_publication_readiness.py --skip-git
python -B .\modular_repos\tools\verify_modules.py
python -B .\modular_repos\tools\verify_split_parity.py
python -B .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
python -B .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py --local-only
python -B .\modular_repos\tools\check_publication_readiness.py --skip-git
```

Fresh install issue found:

```text
uv sync --locked --all-groups
```

failed on Windows while building `pygrib==2.1.8` because the local host lacks
the native ECMWF ecCodes headers (`eccodes.h`). The Docker image handles this by
installing `libeccodes-dev` before `uv sync`. For Windows/local developer
fresh-checkout tests, either use WSL/Linux with ecCodes installed, keep GRIB
dependencies optional, or run the full crawler path through Docker.

## Full Local Function Test

The full function test passed again on 2026-06-05 in the existing configured
workspace:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

Result summary:

- module scaffold verifier: passed
- split parity verifier: passed
- crawler registry audit: passed
- deployment verifier: passed
- Python compile checks: passed
- crawler-pack tests: 3 passed
- post-scripts tests: 3 passed
- scheduler/UI tests: 31 passed, 1 `datetime.utcnow()` warning
- post CLI checks: passed
- scheduler planning: 47 crawlers, 5 planned jobs, 0 plan errors
- Compose config checks: passed
- isolated DB smoke: passed
- real SMARD crawler plus SMARD post-run: passed
- active configured crawler smoke: passed
- local stack smoke: passed
- Docker leftover check: passed

Database evidence from the real crawler smokes:

| Crawler | Evidence |
| --- | --- |
| `smard` | `8064` source rows, `672` price rows, `8064` gapfilled rows |
| `entsoe_api` | `193` `entsoe_api.day_ahead_prices` rows |
| `entsoe_fms` | `27695` `entsoe_fms."EnergyPrices"` rows |
| `power_system_data` | `165064` `power_system_data.powersystemdata` rows |
| `weather_forecast` | `1` `weather.hourly_forecast` row |

## Crawler Coverage

Registry audit:

- merged crawler count: `47`
- upstream OEDS registry count: `32`
- KIT/oeds-crawler-pack registry count: `21`
- unsupported constructors: none
- plan errors in current config: none

Real DB-backed smoke coverage currently includes:

- active KIT/OEDS-KIT crawlers: `entsoe_api`, `entsoe_fms`,
  `power_system_data`, `weather_forecast`
- additional real crawler smoke: `smard`

Import/constructor compatibility is verified for both upstream OEDS and KIT
crawler-pack entries. One upstream special case remains:

- `eex` imports and constructs, but the class has no scheduler-recognized
  `run`, `crawl_temporal`, or `crawl_structural` method. The upstream module
  exposes a module-level `main(schema_name)` instead and requires mirrored EEX
  subscription data. This should become either an upstream `run()` method or a
  scheduler/deployment adapter before claiming scheduler compatibility for
  `eex`.

Not all optional disabled crawlers have real source runs yet. They require
credentials, subscriptions, accepted terms, SFTP access, or large downloads.
Known examples:

- `copernicus_cds`
- `dwd`, `dwd_cdc`, `ecmwf_crawler`, `open_meteo`, broader weather downloads
- `eex`
- `eia`
- `epex_spot`
- `gie_agsi_alsi`, `gie_crawler`
- `mastr`
- `netztransparenz`
- `ninja`
- `prisma_capacity`
- `regelleistung`
- `tradinghub`

## Next Actions

1. Decide remote names and create the four primary add-on remotes.
2. Create initial commits in the four primary add-on repos.
3. Run `check_publication_readiness.py --strict-git`.
4. Run a true fresh clone once the remotes exist.
5. Resolve the Windows fresh-install `pygrib`/ecCodes issue for local developer
   onboarding or document Docker/WSL as the required path.
6. Add targeted real-run tests for optional disabled crawlers in credentialed
   environments.

## Intern-Test VM Update

The intern-test VM deployment smoke was executed on 2026-06-11.

Passed:

- destructive uninstall/reset on the VM
- host prep after disabling a broken VM-local MariaDB DNF repo
- install from local archive export
- update from local archive export
- Ansible smoke test after install and after update
- Crawler Admin, PostgREST, Grafana, pgAdmin, and PostgreSQL HTTP/DB checks
- scheduler image import check: `22` crawler modules, `0` import failures
- active scheduled jobs: `entsoe_fms:latest_hourly`,
  `entsoe_fms:revision_sweep_daily`, `entsoe_api:forecast_daily`,
  `power_system_data`, `weather_forecast`
- real VM runs for `power_system_data` and `weather_forecast`

Fixes made from the VM run:

- production `config.py` modules are no longer accidentally excluded by the
  broad `.gitignore` rule
- deployment/update now seed static crawler data files into the runtime
  `crawler/data` bind mount

Not covered on the VM yet:

- ENTSO-E API/FMS live runs, because the runtime `.env` did not contain
  `ENTSOE_*` credentials.
