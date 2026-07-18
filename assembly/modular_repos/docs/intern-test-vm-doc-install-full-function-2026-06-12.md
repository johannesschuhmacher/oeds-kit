# Intern-Test VM Documented Install and Full Function Test, 2026-06-12

## Scope

Target host:

```text
iip-vm-oeds-intern-test.iip.kit.edu
```

Source:

```text
C:\Users\js2644\PycharmProjects\oeds
```

The unpublished local working tree was exported to:

```text
/home/oeds/oeds-vm-doc-install-source
```

No GitHub, GitLab, or public remote was used. The VM runtime
`crawler/.env` was preserved and restored after the destructive reset. Secret
values were not written to the result files.

## Documented Install Path

The test followed the documented Ansible path from the exported source:

1. Install base tools from the documentation: `git`, `python3`, `python3-pip`.
2. Ensure Ansible is available.
3. Install Ansible collections from `playbooks/requirements.yml`.
4. Create a local inventory from `inventory.example.yml`.
5. Verify Ansible connectivity with `ansible -m ping`.
6. Run `oeds-install-host-prep.yml`.
7. Run a destructive test-machine uninstall:
   - remove repo
   - remove runtime
   - destroy Docker data
   - remove cached service images
   - keep backups
8. Restore the runtime crawler `.env`.
9. Install with crawler services from `local_worktree`.
10. Run the install smoke test.
11. Run the documented update workflow from the same `local_worktree`.
12. Run the final smoke test.

The complete documented install/update flow passed after the local fixes listed
below.

## Fixes Found During the 2026-06-12 Pass

### `local_worktree` archive permissions

The first documented install attempt failed while unpacking the Ansible-created
worktree archive:

```text
Permission denied
```

Fix:

- `playbooks/tasks/oeds-repo-prepare.yml` now makes the generated
  `local_archive`/`local_worktree` tarball readable by the `unarchive` action.
- The same change was copied into
  `modular_repos/modules/oeds-deployment/playbooks/tasks/oeds-repo-prepare.yml`.

### Modular CLI packages missing from the normal crawler image

The first full function run showed that the regular Ansible-installed image
could run the legacy scripts, but not the new modular facades:

```text
python -m oeds_post_scripts.cli
python -m oeds_scheduler_ui.cli
```

Fix:

- `docker/Dockerfile.crawler` now copies:
  - `oeds_post_scripts`
  - `oeds_scheduler_ui`
  - `modular_repos/docs`
  - `modular_repos/sources/oeds-core`
- The image now provides lightweight entrypoints:
  - `oeds-post`
  - `oeds-scheduler`
  - `oeds-crawler-admin`
- The deployment-module Dockerfile copy was synchronized.

### Minimal smoke configs

The first custom function runner used too-small location/variable configs for
three crawlers. The crawlers were correct; the test config was incomplete.

Corrected smoke configs:

- `weather_forecast`: location config now includes country, region, and type.
- `open_meteo`: location config uses the crawler's expected `id` field.
- `dwd_cdc`: variable config includes `path` and `prefix`.

## Final Install Smoke Result

After a fresh destructive uninstall and reinstall, the final smoke summary was:

```text
PostgreSQL 18.3
non_system_tables=49
postgrest=http://127.0.0.1:3001/
grafana=http://127.0.0.1:3006/api/health
```

The running stack after the full function test:

| Service | Result |
| --- | --- |
| `open-data` | up and healthy |
| `postgrest` | up on `127.0.0.1:3001` |
| `grafana` | up on `127.0.0.1:3006` |
| `pgadmin` | up on `127.0.0.1:8080` and `127.0.0.1:8443` |
| `oeds-crawler-admin` | up on `127.0.0.1:3010` |
| `oeds-scheduler` | up after the isolated tests |

## Host and UI Checks

All host-side checks passed:

| Check | Result |
| --- | --- |
| PostgREST root endpoint | passed |
| Grafana health endpoint | passed |
| pgAdmin landing page | passed |
| Crawler Admin health endpoint | passed |
| Crawler Admin dashboard | passed |
| Crawler Admin config editor | passed |
| Crawler Admin gapfill view | passed |
| `oeds_post_scripts` list command via module path | passed |
| `oeds_post_scripts` config migration via module path | passed |
| `oeds_post_scripts` print-command path | passed |
| `oeds_scheduler_ui` one-shot planning via module path | passed |

## Container Command Checks

All runtime-image command checks passed, except the intentionally skipped unit
test step because the runtime image does not ship the test suite.

| Command check | Result |
| --- | --- |
| Compile core, crawlers, admin, scripts, post CLI, scheduler CLI | passed |
| Selected unit tests inside runtime image | skipped, tests are not packaged in runtime image |
| `scripts/gapfill_timeseries.py --list-tables` | passed |
| `scripts/gapfill_timeseries.py --self-test` | passed |
| `scripts/run_price_forecast.py --self-test --model-backend ridge` | passed |
| `scripts/refresh_entsoe_availability_map.py` | passed |
| `scripts/backfill_entsoe_unavailability.py --help` | passed |
| `python -m oeds_post_scripts.cli --list --json` | passed |
| `oeds-post --list` | passed |
| `python -m oeds_scheduler_ui.cli --once` | passed |
| `oeds-scheduler --once` | passed |
| `scripts/gapfill_smard.py` | passed |

## Crawler Results

All import checks for the 21 current KIT crawler modules passed.

Bounded live runs:

| Crawler | Result | Evidence |
| --- | --- | --- |
| `ninja` | passed | smoke mode wrote 3 rows each to `capacity_wind_on`, `capacity_wind_off`, `capacity_solar_merra2` |
| `smard` | passed | `smard=8064`, `prices=672` |
| `entsoe_api` | passed | `day_ahead_prices=192` |
| `entsoe_fms` | passed | `EnergyPrices=55439`, `powersystemdata=165064` |
| `power_system_data` | passed | `powersystemdata=165064`, `eic_geo_location=3016` |
| `weather_forecast` | passed | `hourly_forecast=1`, `locations=1`, `entsoe_country_aliases=17` |
| `open_meteo` | passed | `hourly_forecast=168`, `locations=1` |
| `entsog` | passed | multiple reference/flow tables, total rows greater than 39000 |
| `regelleistung` | passed | `tender_files=6`, `file_rows=2232`, `numeric_values=2232` |
| `osm_power` | passed | `power_features=50` |
| `dwd_cdc` | passed | `regional_monthly=2482` |
| `eurostat_crawler` | passed | `eurostat=2226` |
| `tradinghub` | passed | `report_rows=122`, `report_values=888` |
| `gie_agsi_alsi` | passed structurally | credentials configured, access status written, no inventory rows in the small one-day window |
| `eia` | passed structurally | credentials configured, access status written, no API rows in the small one-day window |
| `netztransparenz` | passed | `endpoint_runs=7`, `raw_rows=1630`, `normalized_values=1139` |
| `epex_spot` | passed | `intraday_auction_prices_volumes=1440` |
| `energy_forecast_crawler` | passed | `predictions_48h=1` |
| `copernicus_cds` | passed | `requests=1`, `downloaded_files=1` |

Skipped live runs:

| Crawler | Reason |
| --- | --- |
| `prisma_capacity` | `PRISMA_API_TOKEN` was not configured on the VM |
| `mastr` | import tested only; the crawler still lacks a bounded smoke mode and would download the complete export |

## Post-Script Evidence

SMARD post-processing passed:

| Table | Rows |
| --- | ---: |
| `smard.smard` | 8064 |
| `smard.prices` | 672 |
| `smard.smard_gapfilled` | 8064 |

ENTSO-E availability map refresh passed in skip-safe mode when the optional
source tables are unavailable.

## Local Validation After VM Test

Local checks after the VM run:

| Check | Result |
| --- | --- |
| `.venv` selected unit tests | passed, 28 tests |
| `modular_repos/tools/verify_split_parity.py` | passed |
| `modular_repos/tools/verify_modules.py` | passed |
| `modular_repos/tools/check_publication_readiness.py` | passed with expected remote/git warnings |
| `sphinx -b dummy docs/source docs/_build/dummy` | passed |

The system `uv` command on this Windows host still resolves to an older global
binary without admin rights, but the project wrapper
`modular_repos/tools/uv.cmd` resolves to user-local `uv 0.11.17`, which is in
the configured project range `>=0.11.7,<0.12`.

## Remaining Release Notes

- Decide the public remote names and create the remotes.
- Keep `crawler_core`, `BaseCrawler`, runtime DB URI handling, and shared
  crawler contracts in the OEDS core repository.
- Add a bounded MaStR smoke mode before claiming live coverage for MaStR.
- Add a PRISMA live smoke only after a token and subscribed package are
  available.
- Consider adding wider windows for EIA and GIE when those data sources need
  row-count guarantees, because the current small windows validate access and
  schema behavior but did not return data rows.
- The VM package manager reports duplicate `crb` and `docker-ce-stable`
  repository definitions. This is harmless for the OEDS install, but should be
  cleaned up in VM base provisioning.
