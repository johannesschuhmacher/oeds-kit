# Local Worktree Split Plan

This plan groups the current local changes into future commit/repository units.
It is a local preparation aid only; no remote has been created or pushed.

## Commit Group 1: OEDS Core Crawler Contract

Target:

```text
open-energy-data-server
```

Files and topics:

- `crawler_core/`
- `crawler/common/base_crawler.py`
- `crawler/common/runtime_env.py`
- `crawler/ninja.py`
- `CRAWLER_CONFIG.yml`
- `docker/initdb/09-bootstrap-roles.sh`
- `.gitattributes`
- crawler docs under `docs/source/crawlers/`

Purpose:

- keep `crawler_core` in the OEDS core
- document the shared crawler contract
- add bounded Ninja smoke mode
- enforce LF for shell scripts used inside Linux containers

## Commit Group 2: Deployment and Ansible

Target:

```text
oeds-deployment
```

Files and topics:

- `playbooks/`
- `docker/`
- `compose.yml`
- `modular_repos/modules/oeds-deployment/`

Purpose:

- support `local_worktree` for unpublished local VM tests
- keep `local_archive` for committed refs
- preserve runtime files outside the repo checkout
- keep deployment copy byte-identical where parity is required

## Commit Group 3: Scheduler and Admin UI

Target:

```text
oeds-scheduler-ui
```

Files and topics:

- `crawler_admin/`
- `crawler_admin_server.py`
- `crawler_scheduler.py`
- `modular_repos/modules/oeds-scheduler-ui/`

Purpose:

- keep scheduler/admin ownership separate from crawler implementation
- preserve current KIT behavior through copied admin UI and scheduler facades

## Commit Group 4: Post-Scripts

Target:

```text
oeds-post-scripts
```

Files and topics:

- `scripts/`
- `scripts/lib/`
- `oeds_gapfill/`
- `oeds_price_forecast/`
- `modular_repos/modules/oeds-post-scripts/`
- `modular_repos/generated/CRAWLER_CONFIG.post.yml`

Purpose:

- expose stable `oeds-post ...` commands
- keep gapfill, forecast, refresh, and backfill behavior reproducible
- avoid direct scheduler dependency on legacy script paths

## Commit Group 5: Compatibility Metadata and Docs

Target:

```text
oeds-deployment
```

Files and topics:

- `modular_repos/modules/oeds-deployment/compatibility.yml`
- `modular_repos/docs/`
- root `README.md`
- `INSTALLATION.md`
- `docs/source/`

Purpose:

- document the module boundaries
- pin compatible local components
- record VM test reports
- collect repository naming options

## Current Local Verification

Latest verified checks:

```text
python -m py_compile crawler\ninja.py tests\test_ninja_crawler.py scripts\refresh_entsoe_availability_map.py scripts\lib\gapfill.py
python -m unittest tests.test_ninja_crawler
python modular_repos\tools\verify_split_parity.py
python modular_repos\tools\verify_modules.py
python -B modular_repos\tools\check_publication_readiness.py
```

VM validation:

```text
modular_repos/docs/intern-test-vm-fresh-checkout-2026-06-11.md
modular_repos/docs/intern-test-vm-full-function-test-2026-06-11.md
```

## Before First Public Commit

- review `git status --short`
- decide final repo names
- remove or intentionally keep generated docs/examples
- run `check_publication_readiness.py --strict-git` after local commits and
  remotes exist
- run one final fresh install from committed refs
