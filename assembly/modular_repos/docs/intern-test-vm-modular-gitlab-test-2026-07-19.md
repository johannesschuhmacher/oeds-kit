# Intern-Test VM Modular GitLab Test - 2026-07-19

## Scope

Validated the modular OEDS deployment flow on
`iip-vm-oeds-intern-test.iip.kit.edu` after publishing the split repositories
to GitLab.

The VM currently cannot clone the private GitLab repositories directly over
HTTPS without credentials. The tested workspace was therefore assembled locally
from the freshly pushed GitLab repositories, archived without VCS/runtime/cache
content, copied to the VM, and installed from that workspace with
`oeds_repo_source_mode=local_worktree`.

## Tested Revisions

- `oeds-deployment`: `b2a52f3` (`Add Linux smoke test scripts`)
- `oeds-crawler-pack`: `24dda880d1ca0a58e592d0b31baa4fbeac7064bc`
- `oeds-scheduler-ui`: `a43d031b13ef271fb6e495c62859c90f9a6975a6`
- `oeds-post-scripts`: `af40b678af67b784e17ed68f8e07f9243519006e`
- `oeds-core`: `6d6d228f00798be3652406620959ee99080c2768`
- `oeds-kit-source`: `0e3ee0b8223750d9ebda3bac0793c0cbeaeb06ea`

## VM Workspace

- transferred workspace:
  `/home/oeds/oeds-modular-transfer-20260718-000226/workspace`
- deployed repo:
  `/open_energy_data_server/repo`
- modular deployment checkout:
  `/open_energy_data_server/repo/modular_repos/modules/oeds-deployment`
- runtime env:
  `/open_energy_data_server/runtime/crawler/.env`
- pre-reset runtime backup:
  `/home/oeds/oeds-runtime-backup-20260719-000318.tar.gz`

## Ansible Results

Validated with the local inventory `/tmp/oeds-local-inventory.yml` and
`--become-password-file /home/oeds/.oeds-sudo.3NEKWQ`.

Passed:

- `oeds-uninstall.yml` with full reset:
  `oeds_uninstall_remove_repo=true`,
  `oeds_uninstall_remove_runtime=true`,
  `oeds_uninstall_destroy_data=true`,
  `oeds_uninstall_confirm=DELETE_OEDS_DATA`
- `oeds-install-crawlers.yml` from `local_worktree`
- built and started modular crawler/admin images through
  `compose.yml + compose.modular.yml`
- built runtime `.env` at the modular compose directory
- `oeds-smoke-test.yml -e oeds_expect_crawler_admin=true`
- `oeds-update.yml` from `local_worktree`
- explicit smoke test after update

The running scheduler command after install was:

```text
oeds-scheduler --config /app/CRAWLER_CONFIG.yml --inventory /app/modular_repos/docs/crawler-inventory.json --workspace-root /app/modular_repos --daemon
```

The running admin command after install was:

```text
oeds-crawler-admin
```

## Functional Smoke Results

The VM does not have `pwsh`, so Linux Bash equivalents were added and tested.

Passed:

- `sudo bash ./tools/test_db_smoke.sh`
- `sudo bash ./tools/test_stack_smoke.sh`
- `sudo bash ./tools/test_real_crawler_smoke.sh --run-post-scripts`
- `sudo bash ./tools/test_active_crawlers_smoke.sh --include-entsoe-fms`

Observed row counts from disposable DB tests:

| Test | Result |
| --- | --- |
| SMARD crawler | `smard.smard`: 8064 rows |
| SMARD prices | `smard.prices`: 672 rows |
| SMARD post-script | `smard.smard_gapfilled`: 8064 rows |
| ENTSO-E API day ahead | `entsoe_api.day_ahead_prices`: 192 rows |
| Power system data | `power_system_data.powersystemdata`: 165064 rows |
| Weather forecast | `weather.hourly_forecast`: 1 row |
| ENTSO-E FMS | `entsoe_fms."EnergyPrices"`: 87983 rows |

## Findings

- The modular Ansible path needed configurable `oeds_compose_dir` and
  `oeds_compose_files`; this was implemented in `oeds-docker-config.yml`,
  `oeds-update.yml`, and `oeds-uninstall.yml`.
- Linux smoke tests are necessary because the target VM has no `pwsh`.
- Disposable runtime directories created by Linux smoke tests must be writable
  by the non-root container user. The Bash scripts set `chmod -R 0777` on their
  temporary runtime directories, matching the broad permissions already used by
  the Ansible runtime directory setup.
- `test_active_crawlers_smoke.sh` needs to discover the installed runtime
  `.env`, not only a local repo-root `crawler/.env`. The script now checks
  `OEDS_CRAWLER_ENV_FILE`, repo-root `.env`, the modular compose `.env`, and
  `/open_energy_data_server/runtime/crawler/.env`.
- Python 3.14 still emits non-blocking `SyntaxWarning`s from the existing
  `crawler/nrw_kwp_waermedichte.py` Windows path strings.
- Direct private GitLab checkout on the VM remains blocked until a deploy key,
  PAT, or readable mirror is configured.

## Status

The modular deployment is functionally validated on the Intern-Test VM via a
freshly assembled GitLab source bundle. Direct VM-side GitLab cloning is the
remaining infrastructure gap, not an application/runtime failure.
