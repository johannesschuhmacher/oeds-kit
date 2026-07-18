# Intern-Test VM Test Plan

This guide describes how to test the modular OEDS structure on the internal
`oeds-intern-test` VM before publishing the module repositories.

## Goal

Validate that the current modular OEDS split can be installed and operated on a
Linux VM, not only on the local Windows/Docker Desktop development machine.

The VM test should prove:

- the deployment playbooks can install the current unpublished local state
- Docker Compose starts the database and access services
- scheduler and crawler admin are reachable
- the modular repository content is present on the VM
- crawler registry and scheduler planning work on the VM
- selected real crawlers can write rows into the VM database
- runtime data, secrets, logs, and Docker state stay outside the repository

## Current Known Blocker

SSH authentication is not working yet.

Observed status:

- TCP port `22` on `iip-vm-oeds-intern-test.iip.kit.edu` is reachable
- WSL has Ansible installed
- `ssh oeds@iip-vm-oeds-intern-test.iip.kit.edu` fails with permission denied
- `ansible -i inventory.yml oeds -m ping` fails with SSH authentication denied

Do not start the deployment steps until SSH access works.

## Shell Conventions

This guide uses two shells:

- PowerShell for Windows-local file preparation.
- WSL Bash for Ansible commands.

Do not run Bash paths or Bash environment assignments directly in PowerShell.

PowerShell path:

```powershell
C:\Users\js2644\PycharmProjects\oeds\playbooks
```

WSL path for the same directory:

```bash
/mnt/c/Users/js2644/PycharmProjects/oeds/playbooks
```

PowerShell environment variable syntax:

```powershell
$env:ANSIBLE_CONFIG = "ansible.cfg"
```

Bash environment variable syntax:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m ping
```

From PowerShell, run WSL commands with `wsl bash -lc`:

```powershell
wsl bash -lc "cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks && ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m ping"
```

## Phase 0: Decide Test Safety Level

Before changing the VM, decide whether it is disposable.

Recommended for a true release test:

- treat `oeds-intern-test` as disposable
- remove old containers and volumes before the final test
- deploy into the existing test path `/open_energy_data_server`

Safer alternative:

- run a database backup first
- do not destroy Docker volumes
- accept that old runtime data may influence the test

Use the destructive reset only after explicit confirmation that the VM can be
recreated or data loss is acceptable.

## Phase 1: Fix SSH Access

Test direct SSH from Windows:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 oeds@iip-vm-oeds-intern-test.iip.kit.edu hostname -f
```

Test direct SSH from WSL:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 oeds@iip-vm-oeds-intern-test.iip.kit.edu hostname -f
```

If this fails:

- install the correct public key for user `oeds` on the VM
- or change `playbooks/inventory.yml` to a different sudo-capable user
- or run the test from a control node that already has SSH access

Expected direct SSH result:

```text
iip-vm-oeds-intern-test.iip.kit.edu
```

If SSH works from Windows only with an explicit key, make the same key available
to WSL before running Ansible. From PowerShell:

```powershell
wsl bash -lc "mkdir -p ~/.ssh && cp /mnt/c/Users/js2644/.ssh/oeds_intern_test_ed25519 ~/.ssh/oeds_intern_test_ed25519 && chmod 700 ~/.ssh && chmod 600 ~/.ssh/oeds_intern_test_ed25519"
```

Then test SSH from WSL with the copied key:

```powershell
wsl bash -lc "ssh -i ~/.ssh/oeds_intern_test_ed25519 -o BatchMode=yes -o ConnectTimeout=10 oeds@iip-vm-oeds-intern-test.iip.kit.edu hostname -f"
```

For Ansible, either add the key path temporarily in `playbooks/inventory.yml`:

```yaml
ansible_ssh_private_key_file: ~/.ssh/oeds_intern_test_ed25519
```

or pass it on the command line:

```powershell
wsl bash -lc "cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks && ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m ping -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519'"
```

Then test Ansible from WSL:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks
ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m ping
```

Equivalent command from PowerShell:

```powershell
wsl bash -lc "cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks && ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m ping"
```

Expected Ansible result:

```text
oeds-intern-test | SUCCESS
```

## Phase 1b: Verify Sudo / Become Access

The inventory uses:

```yaml
ansible_become: true
ansible_become_method: sudo
```

If Ansible returns `Missing sudo password`, SSH is working but the VM does not
allow passwordless sudo for the selected user. Choose one of these options:

- run Ansible interactively with `--ask-become-pass`
- configure passwordless sudo for the test user on the VM
- switch `ansible_user` to another sudo-capable user

For the current test, prefer the interactive password prompt. Start an
interactive WSL shell from PowerShell:

```powershell
wsl
```

Then run:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks
ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m command -a 'whoami' \
  --become \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519'
```

Expected result:

```text
root
```

If the sudo password is not available, stop here and ask the VM administrator
to either provide the password or configure passwordless sudo for the `oeds`
test user.

## Phase 2: Create a Clean Local Test Export

Do not deploy the live working tree directly.

Reason: Ansible `local_archive` uses `git archive`. It packages the selected
Git ref, not arbitrary uncommitted files. Since the modular split is still
unpublished and not committed to public remotes, create a temporary clean export
and commit that export locally.

From PowerShell:

```powershell
$source = "C:\Users\js2644\PycharmProjects\oeds"
$export = Join-Path $env:TEMP "oeds-vm-test-export"

if (Test-Path $export) {
    Remove-Item -LiteralPath $export -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $export | Out-Null

$excludeDirs = @(
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tmp",
    "docker_data",
    "runtime",
    "logs",
    "crawler_admin_state",
    "build",
    "dist"
)
$excludeFiles = @(
    ".env",
    ".env.*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.sqlite3",
    "*.db"
)

robocopy $source $export /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}
```

Create a temporary Git commit inside the export:

```powershell
Push-Location $export
git init
git add .
git -c user.name="OEDS VM Test" -c user.email="oeds-vm-test@example.invalid" commit -m "intern-test modular OEDS export"
Pop-Location
```

Run quick export checks:

```powershell
Push-Location $export
python -B .\modular_repos\tools\check_publication_readiness.py --skip-git
python -B .\modular_repos\tools\verify_modules.py
python -B .\modular_repos\tools\verify_split_parity.py
python -B .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py --local-only
python -B .\modular_repos\tools\check_publication_readiness.py --skip-git
Pop-Location
```

All checks should pass before deploying to the VM.

## Phase 3: Optional VM Backup or Reset

Backup first if the VM contains useful data:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks
ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-db-backup.yml \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519'
```

Destructive reset for disposable VM tests:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks
ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-uninstall.yml \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519' \
  -e oeds_uninstall_destroy_data=true
```

Do not run the destructive reset on a VM with data that must be preserved.

## Phase 4: Deploy the Local Export with Ansible

Use the temporary export through `local_archive`.

From WSL:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks

ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-install-host-prep.yml \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519'

ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519' \
  -e oeds_repo_source_mode=local_archive \
  -e oeds_repo_local_src=/mnt/c/Users/js2644/AppData/Local/Temp/oeds-vm-test-export \
  -e oeds_repo_version=HEAD \
  -e oeds_enable_crawlers=true \
  -e oeds_expect_crawler_admin=true
```

This playbook path should:

- install required host packages if needed
- deploy the local archive into `/open_energy_data_server/repo`
- create runtime directories outside the repo
- start Docker Compose with crawler services enabled
- run the built-in smoke test

Expected result:

```text
failed=0
```

## Phase 5: Run Explicit Service Smoke Test

Run the smoke test again explicitly:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks

ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-smoke-test.yml \
  --ask-become-pass \
  -e 'ansible_ssh_private_key_file=~/.ssh/oeds_intern_test_ed25519' \
  -e oeds_expect_crawler_admin=true
```

This checks:

- PostgreSQL TCP port
- database container running
- PostgreSQL query execution
- non-system table count
- PostgREST endpoint
- Grafana health endpoint
- pgAdmin landing page
- crawler admin UI

## Phase 6: Verify Modular Content on the VM

Run remote shell checks:

```bash
cd /mnt/c/Users/js2644/PycharmProjects/oeds/playbooks

ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m shell -a \
  'test -f /open_energy_data_server/repo/modular_repos/modules/oeds-deployment/compatibility.yml'

ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m shell -a \
  'test -f /open_energy_data_server/repo/modular_repos/modules/oeds-deployment/compose.modular.yml'

ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m shell -a \
  'test -f /open_energy_data_server/repo/modular_repos/tools/verify_modules.py'
```

Expected result for each command:

```text
rc=0
```

## Phase 7: Verify Registry and Scheduler on the VM

Use the scheduler container if it is running. This avoids requiring a full
Python development environment on the VM host.

First inspect containers:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m shell -a \
  'cd /open_energy_data_server/repo && docker compose ps'
```

Then run scheduler planning inside the scheduler container:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible -i inventory.yml oeds -m shell -a \
  'cd /open_energy_data_server/repo && docker compose --profile crawlers exec -T scheduler oeds-scheduler --config /app/CRAWLER_CONFIG.yml --inventory /app/modular_repos/docs/crawler-inventory.json --workspace-root /app/modular_repos --once'
```

Expected planning result:

```text
crawlers: 47
plan errors: 0
```

## Phase 8: Crawler Test Strategy

Do not enable and run every crawler at once.

Use three levels:

1. Registry and constructor compatibility for all crawlers.
2. Reduced-window real DB smoke for active/public crawlers.
3. Credentialed real runs for crawler-specific secrets and subscriptions.

Currently proven by local full function test:

- `smard`
- `entsoe_api`
- `entsoe_fms`
- `power_system_data`
- `weather_forecast`

The VM should repeat these first.

Credentialed or heavy crawlers should be tested in separate runs:

- `copernicus_cds`
- `eia`
- `epex_spot`
- `gie_agsi_alsi`
- `netztransparenz`
- `prisma_capacity`
- `eex`
- larger weather and download crawlers

These need source credentials, accepted terms, mirrored files, subscriptions, or
larger storage/runtime windows.

## Phase 9: Preferred Next Tooling Improvement

The current deep local smoke scripts are PowerShell scripts. The VM is Linux.
For repeatable VM validation, add a Linux-compatible smoke runner to
`oeds-deployment`, preferably in Python or Ansible.

Target script:

```text
modular_repos/modules/oeds-deployment/tools/test_vm_active_crawlers.py
```

It should:

- create a reduced temporary crawler config
- run selected crawlers through the scheduler container
- check expected DB tables and row counts
- print JSON results
- clean temporary runtime files

This avoids installing PowerShell on the VM and makes the test suitable for CI
or scheduled internal validation.

## Executed VM Test on 2026-06-11

Target:

- VM: `iip-vm-oeds-intern-test.iip.kit.edu`
- SSH user: `oeds`
- Ansible control mode: local Ansible on the VM with
  `ansible_connection: local`
- export commit tested last: `ce1d585`

Preparation findings:

- SSH key login from Windows worked.
- `sudo` worked for the `oeds` user.
- Ansible was already installed on the VM (`ansible-core 2.20.6`).
- The VM had a broken enabled `mariadb` DNF repository. It blocked package
  installation because DNF could not download metadata for that repository.
  The repository was disabled for the test VM because OEDS does not depend on
  it for Docker/PostgreSQL deployment.

Reset/install/update results:

- `oeds-uninstall.yml` passed with data destruction, repo removal, and runtime
  removal enabled.
- `oeds-install-host-prep.yml` passed after disabling the broken MariaDB repo.
- `oeds-install-crawlers.yml` passed from local archive export.
- `oeds-smoke-test.yml` passed after install and again after update.
- `oeds-update.yml` passed from local archive export with
  `oeds_backup_database=false`.

Issues found and fixed during the VM test:

- `.gitignore` ignored all `config.py` files. This caused
  `oeds_gapfill/config.py` and `scripts/lib/gapfiller/config.py` to be missing
  from `git archive` based deployments, even though the files existed on disk.
  The ignore rules now keep these production modules trackable.
- `/app/crawler/data` is a runtime bind mount. It hides static files copied into
  the image at build time. The deployment and update playbooks now seed the
  static files required by `power_system_data` into the runtime data mount:
  `mapping_eic_to_location.py`, `mapping_p_to_g.json`, and
  `mapping_g_to_p.json`.

Smoke evidence:

- PostgreSQL reachable on `127.0.0.1:6432`.
- PostgREST reachable on `127.0.0.1:3001`.
- Grafana health reachable on `127.0.0.1:3006/api/health`.
- pgAdmin reachable on `127.0.0.1:8080`.
- Crawler Admin reachable on `127.0.0.1:3010/admin`.
- Admin routes checked with HTTP 200:
  `/admin`, `/admin/editor`, `/admin/gapfill`,
  `/admin/crawlers/entsoe_fms`, `/admin/crawlers/entsoe_api`,
  `/admin/crawlers/power_system_data`, `/admin/crawlers/weather_forecast`,
  `/admin/healthz`, and `/admin/api/cron-preview`.

Scheduler/container evidence:

- `22` crawler modules import inside the running scheduler image.
- `0` crawler import failures.
- Active scheduled jobs loaded:
  `entsoe_fms:latest_hourly`, `entsoe_fms:revision_sweep_daily`,
  `entsoe_api:forecast_daily`, `power_system_data`, and
  `weather_forecast`.
- Disabled but importable jobs listed by the scheduler:
  `ninja`, `energy_forecast_crawler`, `open_meteo`, `tradinghub`,
  `osm_power`, `netztransparenz`, `entsog`, `epex_spot`,
  `entsoe_api:training_bootstrap`, `regelleistung`, `smard`, `eia`,
  `copernicus_cds`, `dwd_cdc`, `mastr`, `prisma_capacity`,
  `eurostat_crawler`, and `gie_agsi_alsi`.

Real crawler evidence on the VM:

| Crawler | Result | Evidence |
| --- | --- | --- |
| `power_system_data` | passed | manual Admin run succeeded in `55s`; `power_system_data.powersystemdata=165064`; `power_system_data.eic_geo_location=3016` |
| `weather_forecast` | passed after one transient DNS failure | manual Admin weather-window run for `berlin`, `forecast_hours=1`, `past_hours=0` succeeded in `10s`; `weather.locations=15`; `weather.hourly_forecast=2161` |

Credential status:

- The runtime crawler `.env` contained no `ENTSOE_*` keys on the VM.
- Therefore ENTSO-E API and ENTSO-E FMS live runs were not executed on the VM.
  They are expected to require `ENTSOE_API_KEY` and/or
  `ENTSOE_USERNAME`/`ENTSOE_PASSWORD`.

## Pass Criteria

The VM test is considered passed when:

- Ansible ping works
- deployment from local archive succeeds
- `oeds-smoke-test.yml` succeeds
- modular files are present on the VM
- scheduler planning reports 47 crawlers and 0 plan errors
- selected real crawlers write rows into PostgreSQL
- crawler admin UI returns HTTP 200
- no unexpected Docker restart loops are visible
- runtime data is outside the repository checkout

## Fail Fast Conditions

Stop and fix before continuing if:

- SSH login fails
- Ansible ping fails
- local export verification fails
- `local_archive` does not include `modular_repos`
- Docker Compose cannot build scheduler/admin images
- scheduler planning reports missing crawler specs or plan errors
- database smoke checks fail
- source credentials are missing for a crawler that is expected to run
