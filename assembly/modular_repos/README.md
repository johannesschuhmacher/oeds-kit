# Modular OEDS Split

This directory contains the modular split of the KIT OEDS extension work.
The upstream Open Energy Data Server remains the base. KIT-specific additions
are separated into module repositories so they can later be published and
maintained independently.

## Module Repositories

| Repository | Responsibility | Current status |
| --- | --- | --- |
| `sources/oeds-core` / OEDS core | shared crawler implementation, `crawler_core`, database contract | central crawler base |
| [`modules/oeds-crawler-pack`](https://github.com/johannesschuhmacher/oeds-crawler-pack) | optional KIT crawler registry and preferred crawler specs | private GitHub repository |
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

For a freshly assembled compatibility workspace where the published KIT source
pin can lag behind the split module pins, run the same interface checks without
the byte-for-byte split parity assertion:

```powershell
python .\modular_repos\tools\verify_modules.py --skip-split-parity
```

Run byte-for-byte parity checks for mechanically copied modules:

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

`crawler_core` belongs in OEDS core. The crawler base class, runtime database
URI handling, metadata helpers, and common crawler contract should be updated in
one central place so the same crawlers can be used by plain OEDS, a slim module
setup, or the full KIT stack with scheduler UI and post-processing.

`oeds-crawler-pack` must not become a second base-crawler implementation. It is
only the registry/extension layer used when KIT-specific or improved crawlers
need to be preferred before they are merged into OEDS core.

## Development Rule

Keep shared crawler implementation work in OEDS core. Keep optional crawler
registry or extension selection in `oeds-crawler-pack`. Scheduler,
post-processing, deployment, and compatibility metadata should stay in their
module repositories.

The copied KIT baseline files should stay byte-identical until a deliberate
refactor moves behavior behind stable module interfaces. Add overlays, wrappers,
or adapters first; modify copied implementation files only with an explicit
reason and matching parity/update documentation.

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

The latest intern-test VM fresh-checkout report is:

```text
docs/intern-test-vm-fresh-checkout-2026-06-11.md
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

The module directories are local repository working trees. They still need
their first public commits and remotes. If Git reports `dubious ownership` for
the nested repositories on this machine, fix repository ownership or configure
`safe.directory` before committing.

Each module repository now contains a starter `.github/workflows/ci.yml` for
fast public CI checks. Full Docker, database, and real crawler tests remain part
of the deployment-level verification rather than every module push.
