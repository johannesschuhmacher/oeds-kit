# Intern-Test VM Clean Git Install - 2026-07-22

## Scope

Validated a full clean modular OEDS install on
`iip-vm-oeds-intern-test.iip.kit.edu` directly from the private GitLab module
repositories.

This test used a GitLab group deploy token for `josc` with `read_repository`
scope. The token value was not written to the repository or logs. It was placed
on the VM as a user-readable `0600` environment file for this test.

## Tested Deployment Revision

- `oeds-deployment`: `1354cc5` (`Install crawler env during clean Git rollout`)

The VM cloned `oeds-deployment` from GitLab, assembled the compatible workspace
from `compatibility.yml`, then installed from that assembled workspace.

## Main Command Shape

```bash
export OEDS_GIT_USERNAME=<deploy-token-username>
export OEDS_GIT_TOKEN=<deploy-token-secret>
export OEDS_BECOME_PASSWORD_FILE=/home/oeds/.oeds-sudo

bash ./tools/oeds_clean_install_from_git.sh \
  --reset \
  --crawler-env-file /home/oeds/.oeds-crawler.env.test \
  --load-sample-data \
  --include-entsoe-fms
```

The wrapper performed:

- direct GitLab clone of `oeds-deployment`
- direct GitLab clone of the private module repositories through
  `tools/assemble_workspace.py`
- destructive reset of the test VM OEDS installation
- modular Ansible installation with `compose.yml + compose.modular.yml`
- installation of the crawler runtime `.env` as
  `/open_energy_data_server/runtime/crawler/.env` with `0600` permissions
- Ansible smoke test
- bounded real-data load into the normal installed database

## Results

The final wrapper run ended with `rc=0` and:

```text
sample data load passed
Clean Git-based modular install finished
```

Final service checks:

| Endpoint | Result |
| --- | --- |
| PostgREST | `200` |
| Grafana | `200` |
| Crawler Admin | `307` |

Final Ansible smoke test:

```text
ok=10 changed=0 unreachable=0 failed=0 skipped=1
non_system_tables=71
```

Final row counts in the normal installed database:

| Table | Rows |
| --- | ---: |
| `entsoe_api.day_ahead_prices` | 193 |
| `entsoe_fms."EnergyPrices"` | 106343 |
| `power_system_data.powersystemdata` | 165064 |
| `smard.prices` | 672 |
| `smard.smard` | 8064 |
| `smard.smard_gapfilled` | 8064 |
| `weather.hourly_forecast` | 2161 |

Final running containers:

- `open-data` healthy
- `postgrest`
- `grafana`
- `pgadmin`
- `oeds-scheduler`
- `oeds-crawler-admin`

## Paths And Permissions

Important VM paths:

```text
/open_energy_data_server/repo
/open_energy_data_server/repo/modular_repos/modules/oeds-deployment
/open_energy_data_server/runtime
/open_energy_data_server/runtime/crawler/.env
```

Observed permissions after install:

| Path | Mode / Owner |
| --- | --- |
| `/open_energy_data_server` | `drwxrwxrwx root:root` |
| `/open_energy_data_server/repo` | `drwxr-xr-x oeds:oeds` |
| `/open_energy_data_server/repo/.env` | `rw------- root:root` |
| `/open_energy_data_server/repo/modular_repos/modules/oeds-deployment/.env` | `rw------- root:root` |
| `/open_energy_data_server/runtime` | `drwxrwxrwx root:root` |
| `/open_energy_data_server/runtime/crawler` | `drwxrwxrwx root:root` |
| `/open_energy_data_server/runtime/crawler/.env` | `rw------- root:root` |
| `/open_energy_data_server/runtime/logs` | `drwxrwxrwx root:root` |
| `/open_energy_data_server/runtime/crawler_admin_state` | `drwxrwxrwx root:root` |

## Finding Fixed During Test

The first clean install run reset the runtime and therefore removed
`crawler/.env`. The stack itself installed correctly, but the sample-data load
failed for `entsoe_api` because the ENTSO-E API token was missing.

Fix:

- `tools/oeds_clean_install_from_git.sh` now accepts `--crawler-env-file` and
  `OEDS_CRAWLER_ENV_FILE`.
- The wrapper installs that file after the Ansible install and before optional
  sample-data loading.
- The README and playbook README document the flag.

After this fix, the full clean GitLab install and data load passed.

## Remaining Notes

- Python 3.14 still emits non-blocking `SyntaxWarning`s for legacy regex/path
  strings in an existing crawler module.
- The installed `/open_energy_data_server/repo` comes from the assembled
  workspace archive. The VM still clones all source components directly from
  GitLab; the final installed tree intentionally does not keep one unified
  `.git` repository because the runtime workspace is assembled from multiple
  repositories.
