# Intern-Test VM Test Plan

This is the release test for the modular GitHub structure on
`iip-vm-oeds-intern-test.iip.kit.edu`. Commands are run on the Linux VM unless
the section explicitly says PowerShell.

## Test Objective

The test must prove that a clean machine can use `oeds-deployment` as its only
entry point and obtain:

- the pinned official OEDS core
- all 21 Crawler Pack crawlers
- upstream-only OEDS crawlers
- scheduler and Admin UI
- all stable post-processing commands
- PostgreSQL, PostGREST, Grafana, and PgAdmin
- a persistent runtime layout outside Git checkouts

No `open-energy-data-server-KIT` checkout may be present in the assembled or
installed workspace.

## 1. Verify Access From Windows

```powershell
ssh -i $env:USERPROFILE\.ssh\oeds_intern_test_ed25519 `
  oeds@iip-vm-oeds-intern-test.iip.kit.edu hostname -f
```

Expected host name:

```text
iip-vm-oeds-intern-test.iip.kit.edu
```

Copy the local crawler secrets to a private temporary path. Do not put them in
a repository:

```powershell
ssh -i $env:USERPROFILE\.ssh\oeds_intern_test_ed25519 `
  oeds@iip-vm-oeds-intern-test.iip.kit.edu `
  "mkdir -p ~/.config/oeds && chmod 700 ~/.config/oeds"

scp -i $env:USERPROFILE\.ssh\oeds_intern_test_ed25519 `
  C:\Users\js2644\PycharmProjects\oeds\crawler\.env `
  oeds@iip-vm-oeds-intern-test.iip.kit.edu:.config/oeds/crawler.env

ssh -i $env:USERPROFILE\.ssh\oeds_intern_test_ed25519 `
  oeds@iip-vm-oeds-intern-test.iip.kit.edu `
  "chmod 600 ~/.config/oeds/crawler.env"
```

## 2. Prepare Private Git Access On The VM

Log in to the VM:

```powershell
ssh -i $env:USERPROFILE\.ssh\oeds_intern_test_ed25519 `
  oeds@iip-vm-oeds-intern-test.iip.kit.edu
```

Use a short-lived GitHub token with read access to all four private add-on
repositories:

```bash
read -rsp 'GitHub token: ' OEDS_GIT_TOKEN
export OEDS_GIT_TOKEN
export OEDS_GIT_USERNAME='<github-user>'
```

Clone the deployment entry point interactively once. Use the token as the
password when prompted:

```bash
rm -rf "$HOME/oeds-deployment-test"
git clone https://github.com/johannesschuhmacher/oeds-deployment.git \
  "$HOME/oeds-deployment-test"
cd "$HOME/oeds-deployment-test"
```

## 3. Optional Non-Interactive Sudo

The installer prompts for the sudo password by default. For an unattended test,
store it temporarily outside the checkout:

```bash
install -m 600 /dev/null "$HOME/.config/oeds/sudo-password"
read -rsp 'sudo password: ' SUDO_PASSWORD
printf '%s\n' "$SUDO_PASSWORD" > "$HOME/.config/oeds/sudo-password"
unset SUDO_PASSWORD
export OEDS_BECOME_PASSWORD_FILE="$HOME/.config/oeds/sudo-password"
```

Delete this file immediately after the test.

## 4. Clean Install From GitHub

The following command intentionally removes the old test installation and its
Docker data:

```bash
bash ./tools/oeds_clean_install_from_git.sh \
  --reset \
  --crawler-env-file "$HOME/.config/oeds/crawler.env" \
  --load-sample-data \
  --include-entsoe-fms
```

This command performs clone, compatibility assembly, Ansible host preparation,
destructive uninstall, installation, service smoke test, and bounded real-data
loading.

## 5. Verify The Installed Layout

```bash
test -f /open_energy_data_server/repo/CRAWLER_CONFIG.yml
test -f /open_energy_data_server/repo/modular_repos/sources/oeds-core/oeds/base_crawler.py
test -f /open_energy_data_server/repo/modular_repos/modules/oeds-crawler-pack/src/crawler/smard.py
test -f /open_energy_data_server/repo/modular_repos/modules/oeds-scheduler-ui/src/oeds_scheduler_ui/cli.py
test -f /open_energy_data_server/repo/modular_repos/modules/oeds-post-scripts/scripts/gapfill_timeseries.py
test ! -d /open_energy_data_server/repo/modular_repos/sources/oeds-kit-current
```

Verify the pinned commits:

```bash
python3 /open_energy_data_server/repo/modular_repos/tools/verify_modules.py
python3 /open_energy_data_server/repo/modular_repos/modules/oeds-deployment/tools/verify_deployment.py
```

## 6. Verify Containers And Registry

```bash
cd /open_energy_data_server/repo/modular_repos/modules/oeds-deployment
docker compose --profile crawlers -f compose.yml ps
docker compose --profile crawlers -f compose.yml exec -T scheduler python - <<'PY'
from oeds_crawler_pack import get_crawler_specs
from oeds_scheduler_ui.application import SchedulerApplication

specs = get_crawler_specs()
assert len(specs) == 21, len(specs)

app = SchedulerApplication(
    "/app/CRAWLER_CONFIG.yml",
    "/app/modular_repos/docs/crawler-inventory.json",
    "/app/modular_repos",
)
assert app.snapshot.crawler_count >= 47, app.snapshot.crawler_count
print({
    "crawler_pack": len(specs),
    "merged_registry": app.snapshot.crawler_count,
    "planned_jobs": app.snapshot.planned_job_count,
})
PY
```

Check the stable post commands:

```bash
docker compose --profile crawlers -f compose.yml exec -T scheduler oeds-post --list
docker compose --profile crawlers -f compose.yml exec -T scheduler \
  oeds-post forecast day-ahead-price --self-test \
  --model-backend ridge --train-days 30 --backtest-days 1
```

## 7. Repeat Integration Tests

```bash
sudo bash ./tools/test_db_smoke.sh
sudo bash ./tools/test_real_crawler_smoke.sh --run-post-scripts
sudo bash ./tools/test_active_crawlers_smoke.sh --include-entsoe-fms
sudo bash ./tools/test_stack_smoke.sh
```

The real-crawler and active-crawler tests must verify non-empty target tables,
not only successful process exit codes.

## 8. Test Update Without Data Loss

```bash
cd /open_energy_data_server/repo/modular_repos/modules/oeds-deployment/playbooks
export ANSIBLE_CONFIG=ansible.cfg

ansible-playbook -i inventory.local.yml oeds-update.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src="$HOME/oeds-modular-git-install/assembled" \
  -e oeds_backup_database=true

ansible-playbook -i inventory.local.yml oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

Record row counts before and after the update for the loaded sample schemas.

## 9. Pass Criteria

- all four add-on repositories and official OEDS match the pinned commits
- no KIT monorepository exists in the assembled workspace
- 21 Crawler Pack specs and at least 47 merged crawler specs are visible
- all service health checks pass
- SMARD source and gapfilled tables contain rows
- active bounded crawlers create their expected tables and rows
- ENTSO-E FMS and API tests pass when credentials and source availability allow
- post-script and forecast self-tests pass
- Admin UI responds and can read/save the runtime configuration
- update preserves the database and runtime configuration
- disposable test containers and volumes are removed after each smoke test

## 10. Cleanup Secrets

```bash
unset OEDS_GIT_TOKEN OEDS_GIT_USERNAME OEDS_BECOME_PASSWORD_FILE
rm -f "$HOME/.config/oeds/sudo-password"
```

Keep `crawler.env` only as long as needed for further VM tests and retain mode
`0600`.
