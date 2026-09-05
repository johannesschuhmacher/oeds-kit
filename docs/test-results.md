# Intern-test results, 2026-09-05

## Latest clean reinstall and crawler fixes

This section supersedes the older installation revisions below. The final
documented application reset/install used fresh private GitHub sources at
deployment `b521741`, core `8a53778`, crawler pack `2f77898`, scheduler/UI
`12bc913` and post-scripts `e1622ff`. Later report-only commits do not change
that runtime. Core `8a53778` is a private test branch based on official OEDS
`38abf45`, not an official upstream release.

The intern-test host remained **CentOS Stream 10**. The operating system was
not reinstalled. Ansible backed up the database, removed OEDS containers,
volumes, source code, runtime and database directories, and retained backups.
Absence of those directories was checked before installation. Host preparation,
database installation, all four Docker stages and explicit post/crawler module
installation completed successfully using [the step-by-step guide](testing.md).
Docker image caches were reused. Production was not touched.

The first repeat exposed a real documentation/test gap: the sample loader used
June 2024, while SMARD's dashboard opens the last 30 days. A browser check showed
empty panels even though SQL against the old date window passed. The loader
now defaults to the preceding chart week; the dashboard test uses the actual
default date windows and requires data from every SQL target. The stricter check
failed on the old sample as expected. A second full reset/install from GitHub
then passed with current samples. Both SMARD panels show series in the browser;
the weather dashboard displays numeric values and its map/series controls.

Completed checks:

- Core and KIT HTTP ZIP fixtures: three tables and 12 exact values per implementation.
- Two real minute-separated scheduler runs, post-run commands and disabling by reload.
- Numerical gapfill and forecast self-tests; all 11 Grafana SQL targets return data.
- Admin form save/restore, cron preview, manual Ninja run with four stored rows,
  gapfill self-tests and a real holdout form submission.
- Ansible update retains SMARD row counts and the exact runtime configuration;
  the complete integration suite passed again after the update.
- Readonly TCP login without INSERT rights, scheduler UID 1000, writable runtime
  paths, root:docker 0640 crawler credentials and localhost-only service ports.
- 90 focused regressions: core 3, crawler pack 18, post-scripts 27, scheduler/UI 33,
  deployment 9. Provider-dependent core tests ran with the full core environment.
- Existing AGPL license texts match the original in all five repositories. No
  actual values from the local credential file were found in tracked files;
  matches were limited to the public Copernicus API URL.

Final installed sample, verified by SQL:

| Dataset | Rows |
| --- | ---: |
| SMARD energy/load / prices / gapfilled | 8,064 / 672 / 8,064 |
| ENTSO-E API prices | 193 |
| ENTSO-E FMS prices / installed-capacity reference | 25,327 / 39,341 |
| Power-plant reference / weather forecast | 165,064 / 24 |
| Consumption / generation outages | 21,139 / 69,737 |

SMARD covers 2026-08-23 22:00 through 2026-08-30 21:45 UTC. The August outage
backfill also refreshed availability-map objects. FMS package selection is
monthly, even when the requested interval is shorter. These counts reflect
publication at test time, not permanent expected values.

The [crawler report](crawler-live-tests.md) documents **36 completed bounded
imports out of 53 implementations** across the full audit and follow-ups.
Twelve corrected implementations were repeated successfully in the freshly built
GitHub runtime; Regelleistung remained partial because one requested FCR dataset
was empty. The other source failures, missing credentials, legacy prerequisites
and unfinished full archives are not declared fixed. No crawler was removed.

All five repositories remain private. SMTP delivery, live Bitwarden integration,
Ubuntu provisioning, full historical imports and every optional research
dashboard are not certified by this run. Upstream merging and public visibility
are separate steps.

Temporary VM Git, sudo and source-credential files were removed, as were the
isolated crawler-test database and network. The installed runtime `.env`, sample
data, backups and six healthy/running services remain; normal crawler schedules
are disabled. The original Windows `.env` is unchanged. Private run logs are at
`/home/oeds/oeds-test-logs-2026-09-05/crawler-fixes`; isolated source logs remain in
`/home/oeds/oeds-crawler-validation/logs` without their temporary environment file.

## Earlier installation audit

The following preserves the earlier test evidence and its original limitations.
Use the latest section above for current revision and installation decisions.

## Environment and scope

Tests ran on `iip-vm-oeds-intern-test.iip.kit.edu`, **CentOS Stream 10**,
using Python 3.13 in the application image, PostgreSQL 18.3, TimescaleDB 2.26.3
and PostGIS. This was a destructive OEDS application reset, not an OS reinstall.
Existing Docker image caches were reused; database and runtime were recreated.
No production services or data were changed.

The documented module-by-module route was exercised first. A second reset used
fresh private GitHub clones and `tools/oeds_clean_install_from_git.sh`, including
host preparation, uninstall, install, service checks and live sample loading.
The complete installer returned zero at deployment commit `a07339c`.
Repeating the installer advanced its existing checkout to `483e231`, preserving
sample data. All follow-up tests passed with that code, including the Ninja
timestamp regression. The subsequent Weather basemap-only correction was checked
separately in Grafana. This is not a blanket certification of every data source.

Official OEDS remains unchanged at `38abf45139f332d59a198c1b0feb95016b323ee1`.
The assembly uses that repository directly, without a KIT monorepository checkout.
Add-ons are selected by `compatibility.yml`:

| Module | Revision |
| --- | --- |
| Crawler pack | `2e1f58df7a8f6f194e61ed20e93c94ab205e8e20` |
| Scheduler/UI | `12bc91392918c1c59a1b66a6174adf04a59634c4` |
| Post-scripts | `e1622ff538565ef92ff1300d85b9933f047f2ae2` |

## Completed lifecycle checks

- Destructive uninstall followed by installation, using the documentation.
- Independent Docker build/import stages: core, crawlers, post and runtime.
- Explicit post-processing SQL installation, separate from DB initialization.
- Ansible update preserved SMARD row counts, runtime configuration and additional
  Compose settings. Password settings are preserved rather than reset.
- Logical globals/database restore into an isolated PostgreSQL 18 staging cluster,
  with restored readonly access and matching SMARD row counts.
- Live cutover and rollback, with matching row counts and service checks after both.
- Ansible password-rotation **dry run** without Bitwarden writes.
- Local deployment regressions: 9 passed. Module CI checks imports and behavior;
  it does not contact external APIs or replace the VM integration tests.
- Final container regressions: crawler pack 5/5, post-scripts 27/27, scheduler/UI
  33/33. One existing `datetime.utcnow()` deprecation warning remains.
- Full `tools/test_installation.sh`: passed, including both crawler fixtures,
  post-processing, real-clock scheduling, HTTP services and 11 Grafana SQL targets.
- Actual admin HTTP form submissions: config save/restore, cron preview, manual
  Ninja smoke run with four SQL rows, gapfill self-tests and holdout tests passed.
  The original disabled configuration was restored afterwards.
- Final Ansible update to `455aaf2`: data/config preserved, service checks and
  all 11 panel queries passed. Readonly TCP login succeeded without INSERT
  privileges. Scheduler UID 1000, runtime write paths, environment injection and
  host secret permissions were verified; published ports bind to localhost.

The deterministic suite downloads local HTTP ZIP fixtures through official OEDS
and the crawler pack, then compares 12 known capacity factors in three tables for
each implementation. The scheduling test waits for two real minute boundaries,
executes the crawler and post-run CLI, and disables the job by config reload.
It also runs numerical gapfill/forecast self-tests.

## Live sample after the GitHub reset

| Table | Rows |
| --- | ---: |
| `smard.smard` | 8,064 |
| `smard.prices` | 672 |
| `smard.smard_gapfilled` | 8,064 |
| `entsoe_api.day_ahead_prices` | 192 |
| `entsoe_fms."EnergyPrices"` | 22,999 |
| `power_system_data.powersystemdata` | 165,064 |
| `weather.hourly_forecast` | 24 |

All five live crawler jobs reported success, including the SMARD post-run.
The FMS sample also loads the installed plant-capacity reference for availability
views. Live counts depend on publication time; do not hardcode them in tests.

The final bounded outage backfill loaded 21,139 consumption outages and 69,677
production/generation outages. Its availability-map refresh
succeeded after the capacity reference was loaded. FMS selection is monthly:
August 1-2 requests still download August packages, not a two-day-only dataset.

## Fixes found by these tests

- FMS uses the writable runtime data path and propagates top-level run failures.
- Post-processing numerical imports no longer require an unrelated crawler runtime.
- Compose settings survive source replacement, including passwords and ports.
- New installs use Docker's built-in local bind-volume driver. Existing volumes
  are not replaced on update. Runtime directories are not world-writable.
- Backup, migration, rollback and password rotation use the module paths.
- PostgreSQL staging data has correct ownership. Role restoration retains the
  source bootstrap grantor; boolean CLI flags work with Ansible 2.20.
- Cutover stops crawlers before backup. Profile containers and their network are
  removed together before restart. Operators must stop external writers separately.
- Credentials are installed before services start. The installer refuses an
  unsafe credential path during reset and advances a reused branch checkout.
- SMARD starter panels use sample tables, English labels and no inherited hidden
  series filter. Specialist dashboards are preserved as optional files.
- Ninja smoke data uses the same `time` column name as the real import.
- The Weather starter map uses OpenStreetMap rather than a default basemap
  displaying a missing API-key watermark. SQL-only tests did not catch this;
  browser inspection did.

## Expanded crawler validation

The later [53-implementation live audit](crawler-live-tests.md) supersedes the
five-source coverage limitation below. It exercised both upstream and KIT
implementations, found additional defects and includes normal-user permission
checks. It does **not** certify every crawler as operational. The earlier
installation, scheduler and dashboard results remain separate evidence.

## Limits and follow-up

- Ubuntu host provisioning and an empty OS image remain untested. Host preparation
  is CentOS-specific and changes SELinux to permissive mode.
- Restore/cutover used PostgreSQL 18 on both sides, not a cross-major upgrade.
- The original five-source sample did not validate every external source.
  The subsequent full inventory audit documents remaining source, subscription,
  implementation and large-download failures individually.
- The merged registry retains 47 names. Legacy upstream `dwd` needs additional
  constructor data; `eex` lacks a recognized scheduler entry point. They are not
  advertised as operational. Use `dwd_cdc` for the modular DWD path.
- Live Bitwarden password rotation and SMTP delivery need separate service access
  and are not covered by these fixture tests.
- Two starter dashboards are tested, not every optional research dashboard.
- Public releases, upstream contributions, the shared Read the Docs site and
  paper publication remain separate work. Only private GitHub test repos changed.

Repeat the checks using [Testing a fresh installation](testing.md).

Raw logs are private on the VM in `/home/oeds/oeds-test-logs-2026-09-05`.
Temporary VM credentials and staging checkouts were removed. The installed
runtime environment, sample data, database backups and six services remain.
