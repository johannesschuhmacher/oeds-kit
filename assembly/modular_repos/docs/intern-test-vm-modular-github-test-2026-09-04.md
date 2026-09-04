# Intern-Test VM Modular GitHub Test - 2026-09-04

## Result

The modular GitHub structure is installable and operable on
`iip-vm-oeds-intern-test.iip.kit.edu`. The official OEDS repository is the
unchanged base. All KIT additions are assembled from separate add-on
repositories; no `open-energy-data-server-KIT` checkout is required.

The clean-install, update, scheduler, post-processing, data persistence, user
rights, and isolated integration checks passed. The repositories remain private
and are not yet tagged as a public release.

## Tested Source Revisions

| Component | Revision | Role |
| --- | --- | --- |
| official OEDS core | `38abf45139f332d59a198c1b0feb95016b323ee1` | unchanged crawler/database base |
| `oeds-crawler-pack` | `581f404398071b3a109a6097c63422cc9a291330` | 21 KIT crawler implementations and temporary compatibility adapters |
| `oeds-scheduler-ui` | `3e8d129fc46cfc03f8944c6d8fb2e5e00ff42936` | scheduler, runtime, and Admin UI |
| `oeds-post-scripts` | `ef800ab36024eb6d09423fb8b49083269aadaa09` | gapfill, forecast, backfill, and refresh jobs |
| `oeds-deployment` | `d758b0f` | Git assembly, Compose, Ansible, and smoke tests |

The generated `assembly.json` reported matching expected and actual commits for
all cloned components.

The VM runtime used scheduler commit `26c1ed5`; `3e8d129` is its documentation-only
descendant and contains no runtime or test-code change.

## Installation Lifecycle

The deployment was tested through the documented GitHub wrapper with a private
read token supplied through the temporary `GIT_ASKPASS` path. The token was not
written into the checkout or assembled workspace.

The earlier destructive qualification run covered:

1. complete Ansible uninstall with repository, runtime, and database removal
2. fresh private GitHub checkout and exact-pin assembly
3. host preparation and Docker installation checks
4. full Ansible crawler-stack installation
5. bounded real-data loading and service verification

The final revision was then tested from another empty work directory without a
database reset. This confirmed that source replacement preserves the external
runtime configuration and Docker-backed database.

During the final documentation-driven run, `--work-dir` exposed an installer
path bug: checkout and assembly paths changed, but the generated inventory kept
the old default path. Commit `d758b0f` fixes this. A second clean checkout from
that commit created and parsed:

```text
/home/oeds/oeds-final-github-release-3/inventory.local.yml
```

The same inventory then ran `oeds-update.yml` successfully. The update created
logical database and globals backups before replacing the installed source and
restarting the stack.

## Service And Rights Checks

The Ansible smoke test passed for:

- PostgreSQL 18.3
- PostgREST
- Grafana
- pgAdmin
- crawler Admin UI
- 99 non-system tables after the functional tests

Runtime ownership was verified as follows:

| Path or container | Effective setting |
| --- | --- |
| crawler credentials | `root:docker`, mode `0640` |
| runtime crawler config | `root:root`, mode `0664` |
| generated Compose `.env` | `root:root`, mode `0644` |
| scheduler container | non-root user `oeds` |
| Admin UI container | root, required for the writable config bind mount |

The Admin UI performed an atomic same-content write against the real mounted
`CRAWLER_CONFIG.yml`. The write succeeded and preserved the configuration hash
`49a8f7539fdf...` before and after install and update.

## Scheduler Check

The installed scheduler reported:

```text
crawlers: 47
planned jobs: 5
plan errors: 0
service issues: 0
```

A separate one-minute SMARD configuration exercised schedule parsing, due-time
calculation, queueing, dispatch, crawler execution, and database writes. The due
job `smard:default` completed successfully.

Static compatibility is intentionally more precise than the enabled-job result:
46 of 47 discovered crawler names have a supported constructor. The unregistered
upstream legacy module `dwd` requires an additional `nuts_matrix` argument and a
missing 2021 NUTS shape file, so it remains visible but is not schedulable. The
working modular DWD implementation is `dwd_cdc` from `oeds-crawler-pack`.

The upstream `eex` crawler has a supported legacy constructor but no recognized
run entry point. Neither legacy case is enabled in the operational config.

## Real Crawler And Database Checks

The final isolated active-crawler smoke produced:

| Crawler/output | Rows | Result |
| --- | ---: | --- |
| ENTSO-E API day-ahead prices | 193 | passed |
| ENTSO-E FMS energy prices | 22,807 | passed |
| power-system data | 165,064 | passed |
| EIC location mapping | 3,016 | passed |
| weather forecast | 1 | passed |

The isolated SMARD and post-run smoke produced:

| Output | Rows | Result |
| --- | ---: | --- |
| `smard.smard` | 8,064 | passed |
| `smard.prices` | 672 | passed |
| `smard.smard_gapfilled` | 8,064 | passed |

The normal installed database retained and extended its data across fresh
source installs and the Ansible update. This proves persistence; isolated smoke
projects were removed automatically and did not alter the normal database.

## Post-Script Checks

The following post-processing paths passed against the modular installation:

- SMARD gapfill
- ENTSO-E FMS gapfill self-tests, 3 of 3
- bounded FMS EnergyPrices gapfill with 48 inserted gap rows
- day-ahead price forecast self-test with 96 forecast rows
- forecast backtest aggregate with 96 rows
- bounded ENTSO-E unavailability backfill
- ENTSO-E availability-map refresh

The backfill verification found 15,616 consumption-unit rows, 126,228
production/generation-unit rows, and 39,341 installed-capacity rows. The
availability-map schema contained five views and two materialized views.

The production table includes rows created by an earlier interrupted unbounded
test. The corrected crawler now limits monthly files to the requested period and
raises on failed files; the bounded consumption backfill inserted exactly the
requested October 2026 package.

## Isolated Integration Suite

All scripts completed from the installed GitHub assembly:

```text
test_db_smoke.sh                                      passed
test_real_crawler_smoke.sh --run-post-scripts        passed
test_active_crawlers_smoke.sh --include-entsoe-fms   passed
test_stack_smoke.sh                                   passed
```

The scripts used disposable Compose projects and removed their containers,
networks, volumes, and runtime directories afterward.

## Remaining Release Boundaries

This result validates the architecture and the configured operational feature
set. It does not claim live qualification of every optional crawler: some need
commercial subscriptions, SFTP accounts, API credentials, accepted source
terms, or very large downloads. Those crawlers remain present and statically
audited and should receive source-specific integration tests when their access
requirements are available.

Before a public release, the remaining decisions are repository naming/public
visibility, coordinated release tags, and the upstream OEDS pull requests for
generic crawler-contract and dependency-metadata improvements.
