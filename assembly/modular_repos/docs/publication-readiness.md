# Publication Readiness

This checklist prepares the local modular OEDS split for public repository
publication. It does not replace the full function test. It documents what must
be published, what must stay local, and which checks should pass before tagging
public versions.

## Current State

- The split contains four add-on module repositories under `modules/`.
- The original OEDS repository remains the central crawler and database base.
- KIT-specific scheduler, UI, post-processing, and deployment work is
  separated into add-on repositories. Compatibility metadata lives in
  `oeds-deployment/compatibility.yml`.
- The four add-on repositories are currently private on GitHub. GitHub is the
  primary remote; the previous GitLab remotes are not mirrored automatically.
- The latest complete GitHub/VM function test is documented in
  `docs/intern-test-vm-modular-github-test-2026-09-04.md`.
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
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
python -B .\modular_repos\tools\check_publication_readiness.py
.\modular_repos\tools\run_full_function_test.ps1
```

The full function test should cover:

- module contract verification
- module source and interface verification
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
- run `tools/verify_deployment.py --local-only` for standalone deployment
  repository checks
- run `tools/verify_deployment.py --local-only` and the publication preflight
  for compatibility manifest checks
- run Compose config checks for full deployment workspace changes
- keep full Docker integration and real crawler smokes as a scheduled or manual
  CI job because they require network access, Docker, and test credentials

## Known Boundaries

The merged inventory contains 47 crawler names. Forty-six have a supported
constructor interface; the unregistered upstream legacy `dwd` module remains a
documented unsupported static entry. The VM function test covers the active
operational set plus SMARD and major post-processing paths. Disabled or optional
crawlers still need targeted runs before making broad live-coverage claims,
especially crawlers requiring SFTP, subscriptions, accepted terms, or large
downloads.

- `epex_spot` (SFTP account)
- `prisma_capacity` (subscribed API package)
- `gie_agsi_alsi` and `netztransparenz` (API credentials)
- `copernicus_cds` (account and accepted terms)
- `mastr` (large full-data export)

Remote-host installation and update have been smoke-tested with Ansible. A final
tagged-release repetition remains appropriate after the repositories become
public.

## Git Preparation

The module directories are local repository working trees whose private GitHub
remotes already exist. Before the first public release:

- inspect each module with `git status`
- fix local Git ownership if `dubious ownership` is reported
- verify that each module tracks its GitHub `origin/main`
- make the private repositories public only after local secrets and runtime
  artifacts are confirmed absent

Do not use the root OEDS repository commit as the publication boundary for these
add-on modules. Each module should have its own history, tag, and release notes.

## First Public Tag

1. Review the four private GitHub repositories and their publish exclusions.
2. Run the full local function test from a clean GitHub checkout.
3. Add or enable CI workflows for fast unit and manifest checks.
4. Make the repositories public when the review and clean-install test pass.
5. Tag module repositories with matching release-candidate tags.
6. Update `oeds-deployment/compatibility.yml` from commit pins to tagged
   repository references.
7. Repeat the remote-host deployment smoke with the coordinated release tags.
8. Publish the final deployment-compatible release tag.
