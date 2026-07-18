# Current Modular Split Status

This document records the local repository split state.

## Target Shape

The original OEDS core remains the central base for crawler/database behavior.
KIT-specific additions are split into local module repositories:

| Module repo | Responsibility | Current state |
| --- | --- | --- |
| OEDS core | shared crawlers, `crawler_core`, database contract | central base, keep shared crawler runtime here |
| `oeds-crawler-pack` | KIT crawler registry and preferred crawler specs | implemented as a static/dynamic crawler registry facade |
| `oeds-scheduler-ui` | scheduler runtime, registry planning, admin UI integration | implemented scheduler planning, runtime, daemon, CLI, and copied admin UI |
| `oeds-post-scripts` | gapfill, forecast, refresh, derived-data commands | stable `oeds-post` CLI, copied current implementation, direct-call support where safe |
| `oeds-deployment` | compose, Docker, Ansible, provisioning, ops tooling, compatibility manifest | copied current deployment baseline plus modular overlay and `compatibility.yml` |

## Preserved Center

The split does not duplicate crawler maintenance as the default architecture.
`crawler_core`, `BaseCrawler`, database URI handling, metadata helpers, and the
shared crawler contract belong in OEDS core. The optional registry still
resolves crawlers by source priority:

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

Latest GitLab publication note:

```text
docs/gitlab-publication-2026-07-15.md
```

Latest GitHub experiments repository note:

```text
docs/github-experiments-repo-2026-07-16.md
```

Latest VM reports:

```text
docs/intern-test-vm-doc-install-full-function-2026-06-12.md
docs/intern-test-vm-full-function-test-2026-06-11.md
docs/intern-test-vm-fresh-checkout-2026-06-11.md
```

The 2026-06-12 VM test is the current release-readiness evidence. It covered
the documented setup path step by step, destructive uninstall, local worktree
install, update, smoke tests, runtime image modular CLI availability, Admin UI,
Scheduler, Post-Scripts, database writes, and bounded crawler runs against a
fresh database.

Run the complete local function test:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

Current expected result:

```text
Full Function Test Summary: all steps passed
```

The full runner covers:

- module scaffold and split parity
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
- copied admin UI artifacts
- post-script command registry and config migration
- copied post-script implementation files
- copied deployment files and modular deployment artifacts
- deployment compatibility manifest wiring
- module license files, starter CI workflows, and publication checklist

For publication preflight checks, run:

```powershell
python -B .\modular_repos\tools\check_publication_readiness.py
```

This check rejects local runtime/test artifacts and reports outstanding Git
setup work such as missing remotes or pending initial commits.

## Publication Status

The local modular split has been pushed as private GitLab projects under the
KIT JOSC namespace. The four add-on repositories have initial `main` commits,
track `origin/main`, and were verified through fresh clones from GitLab.

The remaining work is release hardening, compatibility pinning, full
fresh-machine installation from GitLab URLs, and a few bounded crawler-test
gaps, not basic functionality.

## Remaining Work Before Public Release

- Keep `crawler_core` in OEDS core and document the public crawler contract
  there before upstream/public publication.
- Decide whether the current private GitLab project names are final for public
  use. See `docs/repository-naming-options.md`.
- Decide whether generated config examples should be committed in every repo or
  only in `oeds-deployment`.
- Review and enable the prepared per-repo CI workflows after remotes exist.
- Keep `oeds-crawler-pack` optional until crawler ownership is finalized.
- Run one remote-host Ansible deployment smoke from committed refs after the
  first public remotes exist.
- Add separate integration tests for optional disabled crawlers that require
  SFTP access, API subscriptions, or accepted external terms.
- Add or document a bounded MaStR smoke mode equivalent to the new Ninja smoke
  mode.
