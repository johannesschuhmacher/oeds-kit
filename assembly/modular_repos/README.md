# Modular OEDS Split

This directory contains the modular split of the KIT OEDS extension work.
The upstream Open Energy Data Server remains the base. KIT-specific additions
are separated into module repositories so they can later be published and
maintained independently.

## Module Repositories

| Repository | Responsibility | Current status |
| --- | --- | --- |
| `sources/oeds-core` / OEDS core | unchanged official crawler and database implementation | pinned central base |
| [`modules/oeds-crawler-pack`](https://github.com/johannesschuhmacher/oeds-crawler-pack) | KIT crawler implementations, preferred crawler registry, and temporary core adapters | private GitHub repository |
| [`modules/oeds-scheduler-ui`](https://github.com/johannesschuhmacher/oeds-scheduler-ui) | scheduler runtime, daemon, admin UI | private GitHub repository |
| [`modules/oeds-post-scripts`](https://github.com/johannesschuhmacher/oeds-post-scripts) | gapfill, forecast, refresh, derived data tools | private GitHub repository |
| [`modules/oeds-deployment`](https://github.com/johannesschuhmacher/oeds-deployment) | Compose, Docker, Ansible, provisioning, ops, compatibility manifest | private GitHub repository and installation entry point |

## Verification

Run the full local function test:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

This exercises module wiring, unit tests, CLIs, Docker Compose, the disposable
database, a real SMARD run with post-processing, the active configured crawler
set with reduced windows, and the local service stack.

Run the faster standard verification:

```powershell
python .\modular_repos\tools\verify_modules.py
```

For a freshly assembled compatibility workspace, run the interface checks
without the historical byte-for-byte KIT split assertion:

```powershell
python .\modular_repos\tools\verify_modules.py --skip-split-parity
```

The parity check remains available only for comparing still-unmodified files
with the historical KIT source:

```powershell
python .\modular_repos\tools\verify_split_parity.py
```

Run deployment split smoke checks:

```powershell
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
```

Run the publication preflight before initial commits or tags:

```powershell
python -B .\modular_repos\tools\check_publication_readiness.py
```

The parity verifier compares copied post-script, deployment, and admin UI files
with the current KIT checkout. If it passes, these copied modules should
reproduce the same behavior as KIT for those unchanged files, assuming the same
runtime environment, database, credentials, and external data availability.

## Generated Artifacts

`generated/CRAWLER_CONFIG.post.yml` is a migrated copy of the current scheduler
config using stable `oeds-post ...` commands. The operational
`CRAWLER_CONFIG.yml` is not overwritten.

## Core Boundary

The official OEDS checkout is currently consumed unchanged. Generic crawler
contract improvements belong upstream so the same crawlers can eventually be
used by plain OEDS, a slim module setup, or the full stack. Until those changes
are merged, the required `crawler_core` and BaseCrawler compatibility adapters
live in `oeds-crawler-pack`, above the official core.

`oeds-crawler-pack` must not become a second base-crawler implementation. It is
only the registry/extension layer used when KIT-specific or improved crawlers
need to be preferred before they are merged into OEDS core.

## Development Rule

Prepare generic crawler implementation changes as upstream OEDS contributions.
Keep unmerged adapters, KIT crawler implementations, and extension selection in
`oeds-crawler-pack`. Scheduler, post-processing, deployment, and compatibility
metadata stay in their module repositories.

Intentional improvements are verified by module tests and deployment-level
functional tests. Historical byte parity is no longer a release criterion for
files that have been modularized or fixed.

## Publication Boundary

The four module repositories are published privately on GitHub. GitHub is the
current primary remote; the earlier GitLab repositories are retained only as
historical remotes and are not mirrored automatically. Before public release,
review the publication checklist in:

```text
docs/publication-readiness.md
```

The latest release preparation note is:

```text
docs/release-prep-2026-06-05.md
```

The latest intern-test VM modular GitHub report is:

```text
docs/intern-test-vm-modular-github-test-2026-09-04.md
```

Repository naming options are collected in:

```text
docs/repository-naming-options.md
```

The local worktree split/commit grouping is documented in:

```text
docs/local-worktree-split-plan.md
```

Do not publish local `.env` files, runtime state, Docker volumes, generated
temporary test data, or machine-specific IDE files.

The module directories are independent Git working trees whose private GitHub
repositories track `origin/main`.

Each module repository now contains a starter `.github/workflows/ci.yml` for
fast public CI checks. Full Docker, database, and real crawler tests remain part
of the deployment-level verification rather than every module push.
