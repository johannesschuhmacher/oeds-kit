# Publication Readiness

This checklist prepares the local modular OEDS split for public repository
publication. It does not replace the full function test. It documents what must
be published, what must stay local, and which checks should pass before tagging
public versions.

## Current State

- The split contains four primary add-on module repositories under `modules/`
  plus the optional transition module `oeds-crawler-pack`.
- The original OEDS repository remains the central crawler and database base.
- KIT-specific scheduler, UI, post-processing, and deployment work is
  separated into add-on repositories. Compatibility metadata lives in
  `oeds-deployment/compatibility.yml`.
- The latest complete local function test is documented in
  `docs/full-function-test-2026-06-02.md`.
- The full local verification command is:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
```

The latest release preparation note, including remote-name recommendations,
fresh-checkout simulation results, VM test status, and crawler coverage, is:

```text
docs/release-prep-2026-06-05.md
```

## Repository Split

| Repository | Publishes | Depends On |
| --- | --- | --- |
| `oeds-crawler-pack` | Preserved KIT crawler implementations and registry metadata | OEDS core crawler/database conventions |
| `oeds-scheduler-ui` | Scheduler contracts, planner, runtime, daemon, CLI, Admin UI | OEDS core plus `oeds-crawler-pack` registry |
| `oeds-post-scripts` | Stable `oeds-post` CLI and post-processing implementation | OEDS database schema and crawler outputs |
| `oeds-deployment` | Docker Compose overlays, Dockerfiles, Ansible, smoke tests, ops helpers, compatibility manifest | OEDS core plus all add-on modules |

## Publish Only

Publish source code, tests, docs, templates, example configs, manifests,
Dockerfiles, Compose files, Ansible playbooks, and deterministic generated
config examples such as `generated/CRAWLER_CONFIG.post.yml`.

Every module repository should include:

- `README.md`
- `CHANGELOG.md`
- `pyproject.toml` where the module is a Python package
- `uv.lock` where dependency locking is managed locally
- `LICENSES/AGPL-3.0-or-later.txt`
- module-local tests or smoke scripts

## Do Not Publish

Do not publish local secrets, runtime state, generated test environments, or
machine-specific data:

- `.env`
- `.env.*`
- `.tmp/`
- `runtime/`
- `logs/`
- `crawler_admin_state/`
- `docker_data/`
- database dumps unless sanitized and explicitly intended as fixtures
- IDE folders and user-specific editor metadata
- Docker volumes, container state, and local compose project artifacts

## Required Checks

Run these from the workspace root before tagging a public release candidate:

```powershell
python .\modular_repos\tools\verify_modules.py
python .\modular_repos\tools\verify_split_parity.py
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
python -B .\modular_repos\tools\check_publication_readiness.py
.\modular_repos\tools\run_full_function_test.ps1
```

The full function test should cover:

- module contract verification
- copied-artifact parity
- Python compile checks
- module unit tests
- post-script CLI smoke tests
- scheduler planning checks
- Admin UI import check
- Compose configuration validation
- PostgreSQL initialization smoke test
- real SMARD crawler plus post-processing
- active configured crawler smoke test
- full local service stack smoke test
- Docker leftover cleanup check

## CI Plan

Start with lightweight CI per repository:

- use the prepared `.github/workflows/ci.yml` in each module repository
- run unit tests and compile checks for Python packages
- run `verify_modules.py` from the assembled deployment workspace
- run `verify_split_parity.py` against the checked-out KIT reference while
  copied artifacts are still expected to be byte-identical
- run `tools/verify_deployment.py --local-only` for standalone deployment
  repository checks
- run `tools/verify_deployment.py --local-only` and the publication preflight
  for compatibility manifest checks
- run Compose config checks for full deployment workspace changes
- keep full Docker integration and real crawler smokes as a scheduled or manual
  CI job because they require network access, Docker, and test credentials

## Known Boundaries

The local full function test covers the enabled crawler set from the current KIT
configuration plus SMARD post-processing. Some disabled or optional crawlers
still need targeted real runs before making broad public coverage claims:

- `chargepoint`
- `energycharts`
- `entsoe_generation`
- `entsoe_load`
- `entsoe_transparency`
- `federal_grid_agency`
- `market_location`

Remote-host deployment should also be smoke-tested once with Ansible before the
deployment repository is tagged for external operators.

## Git Preparation

The module directories are local repository working trees. Before the first
public push:

- inspect each module with `git status`
- fix local Git ownership if `dubious ownership` is reported
- create an initial commit per module after reviewing publish exclusions
- add public remotes only after local secrets and runtime artifacts are absent

Do not use the root OEDS repository commit as the publication boundary for these
add-on modules. Each module should have its own history, tag, and release notes.

## First Public Tag

1. Create empty public remotes for the four primary add-on module repositories.
2. Create the reviewed initial commit in each local module repository.
3. Push each local module repository without local runtime artifacts.
4. Add CI workflows for fast unit and manifest checks.
5. Run the full local function test from a clean checkout.
6. Tag module repositories with matching release-candidate tags.
7. Update `oeds-deployment/compatibility.yml` from local paths to tagged
   repository references.
8. Run a remote-host deployment smoke test.
9. Publish the final deployment-compatible release tag.
