# Test a fresh installation

Use a disposable Linux VM. Never run the reset on a production server.
The Ansible host setup currently targets CentOS Stream. Ubuntu host setup is
not yet verified; do not treat a CentOS test as an Ubuntu certification.

## 1. Prepare

Install Git, Python 3.12 or newer, and Ansible. Clone `oeds-deployment` and
assemble its pinned dependencies (see the main README). Keep secrets outside
the checkout and installation directory. SSH into the VM; all commands below
run in the VM's Linux terminal, not Windows PowerShell.

```bash
cd "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment/playbooks"
# Change ansible_user in this file if your Linux username is not oeds.
nano inventory.local.yml
ansible-galaxy collection install -r requirements.yml
export ANSIBLE_CONFIG=ansible.cfg
```

Use `-K` to enter your sudo password. For automation, replace `-K` with
`--become-password-file /path/to/file`; protect that file with `chmod 600`.

## 2. Back up, then remove the old installation

Skip the backup command on a genuinely empty machine. A backup can contain
private data and database roles: keep it private.

```bash
ansible-playbook -i inventory.local.yml -K oeds-db-backup.yml
ansible-playbook -i inventory.local.yml -K oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true -e oeds_uninstall_remove_runtime=true \
  -e oeds_uninstall_destroy_data=true -e oeds_uninstall_confirm=DELETE_OEDS_DATA
```

This destroys the OEDS database, Grafana state and runtime settings. Backups
are retained. Save crawler credentials separately before this command.

## 3. Install the database and service stack

```bash
ansible-playbook -i inventory.local.yml -K oeds-install-host-prep.yml
ansible-playbook -i inventory.local.yml -K oeds-install-core.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src="$HOME/oeds-assembled" \
  -e oeds_crawler_env_file="$HOME/crawler.env"
```

The supplied environment file is optional. This installs PostgreSQL/TimescaleDB,
PostGIS, Grafana, pgAdmin and PostgREST, with no scheduled crawler runs.

## 4. Install and check Python modules in order

Docker targets make each dependency boundary independently buildable. The
`core` target installs official OEDS only, `crawlers` adds the crawler pack,
`post` adds post-processing, and `runtime` adds scheduler/UI. Cached layers
are reused. These stages verify installation order, not independent services.

```bash
cd /open_energy_data_server/repo
for stage in core crawlers post runtime; do
  docker build --target "$stage" -t "oeds-test:$stage" \
    -f modular_repos/modules/oeds-deployment/docker/Dockerfile.crawler-modular .
  docker run --rm "oeds-test:$stage" python -c 'import oeds; print("OEDS import OK")'
done
```

Install post-processing database functions explicitly. They are not a
dependency of database initialization:

```bash
cd "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment/playbooks"
ansible-playbook -i inventory.local.yml -K oeds-install-post.yml
ansible-playbook -i inventory.local.yml -K oeds-install-crawlers.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src="$HOME/oeds-assembled" \
  -e oeds_crawler_env_file="$HOME/crawler.env"
```

## 5. Run the small integration suite

Run from the installed deployment directory. These commands write sample data
into the installed test database. Never run them on production.

```bash
cd /open_energy_data_server/repo/modular_repos/modules/oeds-deployment
sudo bash tools/load_sample_data.sh --include-entsoe-fms
sudo bash tools/test_installation.sh
```

The live load uses one SMARD week, a short ENTSO-E API price window, one FMS
price package plus its plant-capacity reference, a power-plant reference dataset and 24 weather forecast hours
for Berlin. ENTSO-E needs your API/FMS credentials. The power-plant reference
is about 165,000 rows; it is optional for the deterministic fixture suite.

The deterministic part serves two four-row CSV files as ZIP downloads over
local HTTP. Official OEDS and the crawler pack must each write the same 12
capacity factors to `oeds_test_core` and `oeds_test_crawlers`. Nothing is
mocked at the HTTP/database boundary. It also checks gapfill/forecast math,
two real one-minute scheduler runs, post-run commands, config reload and all
11 starter-dashboard SQL queries through Grafana. Allow several minutes.

For a bounded real ENTSO-E outage backfill and view refresh:

```bash
docker exec oeds-scheduler oeds-post backfill entsoe-unavailability \
  --start 2026-08-01 --end 2026-08-02
```

FMS downloads monthly packages even for a shorter requested interval. This
checks bounded package selection, not necessarily day-level filtering of rows.
Inspect data and error counts; a successful process exit alone is not enough.

The older four separate smoke scripts in Bash and PowerShell were replaced by
this one integration entry point. Run it on Linux via SSH; no WSL is required.
Keep module behavior/numerical tests as well as this small end-to-end suite.

## 6. Check an update

```bash
cd "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment/playbooks"
ansible-playbook -i inventory.local.yml -K oeds-update.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src="$HOME/oeds-assembled" -e oeds_enable_crawlers=true
ansible-playbook -i inventory.local.yml -K oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

Confirm sample data and configuration survive. A clean application reset is
not an OS reinstall: record the tested OS and external API failures honestly.
