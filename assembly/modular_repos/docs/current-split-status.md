# Current Modular Split Status

This document records the local repository split state.

## Target Shape

The original OEDS core remains the central base for crawler/database behavior.
KIT-specific additions are split into local module repositories:

| Module repo | Responsibility | Current state |
| --- | --- | --- |
| OEDS core | official crawlers and database contract | unchanged pinned central base |
| `oeds-crawler-pack` | KIT crawler implementations, preferred registry, and temporary adapters | installable extension package without KIT-monorepo dependency |
| `oeds-scheduler-ui` | scheduler runtime, registry planning, admin UI integration | implemented scheduler planning, runtime, daemon, CLI, and copied admin UI |
| `oeds-post-scripts` | gapfill, forecast, refresh, derived-data commands | stable `oeds-post` CLI, copied current implementation, direct-call support where safe |
| `oeds-deployment` | compose, Docker, Ansible, provisioning, ops tooling, compatibility manifest | copied current deployment baseline plus modular overlay and `compatibility.yml` |

## Preserved Center

The split does not modify or fork the official OEDS checkout. Generic
`crawler_core`, BaseCrawler, database URI, metadata, and contract improvements
are upstream candidates. Until they are merged, the required compatibility
implementation lives in `oeds-crawler-pack`. The registry resolves crawlers by
source priority:

```text
oeds-crawler-pack before oeds-core
```

This lets current KIT-enhanced crawlers win where needed while upstream-only
OEDS crawlers remain available. The registry layer must not become a second
base-crawler implementation.

## Post-Run Config Migration

The operational `CRAWLER_CONFIG.yml` is not overwritten. A migrated copy exists:

```text
generated/CRAWLER_CONFIG.post.yml
```

Known replacements:

| Old script path | Stable command |
| --- | --- |
| `scripts/gapfill_smard.py` | `oeds-post gapfill smard` |
| `scripts/gapfill_timeseries.py` | `oeds-post gapfill entsoe-fms` |
| `scripts/refresh_entsoe_availability_map.py` | `oeds-post refresh entsoe-availability-map` |
| `scripts/run_price_forecast.py` | `oeds-post forecast day-ahead-price` |

## Verification

Previous GitLab publication note:

```text
docs/gitlab-publication-2026-07-15.md
```

Latest GitHub experiments repository note:

```text
docs/github-experiments-repo-2026-07-16.md
```

Latest VM report:

```text
docs/intern-test-vm-modular-github-test-2026-09-04.md
```

The 2026-09-04 VM test is the current release-readiness evidence. It covered the
documented private-GitHub setup path, prior destructive uninstall, clean exact-pin
assembly, installation, update with backup, smoke tests, Admin UI writes,
short-interval scheduling, Post-Scripts, preserved database data, and bounded
real crawler runs.

Run the complete local function test:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

Current expected result:

```text
Full Function Test Summary: all steps passed
```

The full runner covers:

- module scaffold and interface verification
- crawler registry audit
- module unit tests
- post-script CLI commands
- scheduler planning and Admin UI import
- Compose models
- isolated DB init
- SMARD real crawler plus post-run gapfill
- active configured crawlers with reduced windows
- local PostGREST, Grafana, and Admin UI stack
- Docker/test-cache cleanup

For fast local checks, run:

```powershell
python .\modular_repos\tools\verify_modules.py
```

Current expected result:

```text
modular repository scaffold verification passed
```

The verifier checks:

- crawler registry priority and constructor compatibility
- scheduler planning/runtime/daemon path
- packaged admin UI artifacts
- post-script command registry and config migration
- packaged post-script implementation files
- deployment files and modular deployment artifacts
- deployment compatibility manifest wiring
- module license files, starter CI workflows, and publication checklist

For publication preflight checks, run:

```powershell
python -B .\modular_repos\tools\check_publication_readiness.py
```

This check rejects local runtime/test artifacts and reports outstanding Git
setup work such as missing remotes or pending initial commits.

## Publication Status

The four add-on repositories are published privately under the
`johannesschuhmacher` GitHub account. Their local working trees track the
GitHub `origin/main`; the previous GitLab remotes are retained as `gitlab`
without automatic mirroring. `oeds-deployment/compatibility.yml` pins the
GitHub module URLs and exact tested component commits.

The original `open-energy-data-server/open-energy-data-server` repository
remains the central OEDS core. It is consumed by the modular deployment and is
not duplicated into another add-on repository.

The GitHub-only VM installation and remote Ansible update tests are complete.
Remaining publication work is release naming/tagging and source-specific tests
for optional crawlers that need special external access.

## Remaining Work Before Public Release

- Prepare the generic parts of `crawler_core`, BaseCrawler, and dependency
  metadata as upstream OEDS pull requests. Until merged, keep the compatibility
  adapter in `oeds-crawler-pack`.
- Confirm whether the current private GitHub repository names are final before
  making them public. See `docs/repository-naming-options.md`.
- Review and enable the prepared per-repo CI workflows after remotes exist.
- Add separate integration tests for optional disabled crawlers that require
  SFTP access, API subscriptions, or accepted external terms.
- Add or document a bounded MaStR smoke mode equivalent to the new Ninja smoke
  mode.
