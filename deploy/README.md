# OEDS deployment

Installation, Docker Compose, Ansible and Grafana provisioning for the
[oeds-kit](../README.md) stack. The parts it installs live in this
repository:

| Part | What it does |
| --- | --- |
| [Official OEDS](https://github.com/open-energy-data-server/open-energy-data-server) | Upstream crawler and database library; installed from the [core test branch](https://github.com/johannesschuhmacher/oeds-core) at the revision pinned in the root `pyproject.toml` |
| [Crawler pack](../packages/crawler-pack/README.md) | KIT crawlers, `oeds-crawl`, the `KitCrawler` base class |
| [Scheduler/UI](../packages/scheduler/README.md) | Scheduled jobs (each run is an `oeds-crawl` subprocess), post-run commands and browser administration |
| [Post-scripts](../packages/post/README.md) | Gapfilling, backfill, forecasts and derived database views |
| This directory | Installation, Docker Compose, Ansible and Grafana provisioning |

All Python dependencies come from the root `uv.lock`; the runtime image is
built with `uv sync --frozen` from it (`docker/Dockerfile.crawler-modular`,
build context is the repository root).

## Install on a Linux VM

Run these commands **inside the VM's Linux terminal**, after connecting with
SSH from Windows. Automated host preparation currently targets CentOS Stream;
Ubuntu host preparation has not been validated. You need Git, Python 3.12+,
sudo access and network access to GitHub/container registries.

The repository is public; cloning it requires no GitHub account or token
(`OEDS_GIT_TOKEN` is only needed for private forks). Provider API keys for
credentialed crawlers are separate; keep those in your private environment
file, never in Git.

```bash
git clone https://github.com/johannesschuhmacher/oeds-kit.git
cd oeds-kit
bash deploy/tools/oeds_clean_install_from_git.sh --crawler-env-file "$HOME/crawler.env"
```

The environment file is optional; omit that option for sources without API
keys. The installer asks for your sudo password. Existing database and runtime
settings are preserved. **Do not add `--reset` unless you intend to delete
the old database and runtime settings.** All crawlers start disabled: choose
the sources you need in the admin UI before enabling a schedule.

To load a small real sample after installation, run inside the test VM:

```bash
cd /open_energy_data_server/repo/deploy
sudo bash tools/load_sample_data.sh --include-entsoe-fms
sudo bash tools/test_installation.sh
```

This uses your ENTSO-E credentials and writes test data to the installed database.
The recent SMARD week is visible in the dashboard's default time range.

For a guided, step-by-step installation and test, follow
[Testing a fresh installation](docs/testing.md). For backup, update, migration,
password rotation and removal, see [Operations](playbooks/README.md).

For credentialed checks of all upstream and KIT crawler implementations, use
[Live crawler validation](docs/crawler-live-tests.md). It uses separate databases
and reports source failures and incomplete large imports explicitly.

## Open the applications

Services bind to localhost. On your Windows computer, keep this SSH tunnel open
(replace the username and VM name):

```powershell
ssh -L 3010:localhost:3010 -L 3006:localhost:3006 -L 8080:localhost:8080 user@your-vm
```

- Admin UI: <http://localhost:3010/admin>
- Grafana: <http://localhost:3006> (initial test login `opendata` / `opendata`)
- pgAdmin: <http://localhost:8080> (initial test login `admin@admin.admin` / `admin`)

These are insecure test defaults. The admin UI has no built-in authentication.
Keep it behind SSH or authenticated access; rotate passwords before deployment
on a shared network. See Operations for the password rotation playbook.

## Files you edit

The managed installation lives in `/open_energy_data_server`:

| Path | Purpose |
| --- | --- |
| `repo/` | Installed copy of this repository; replaced by an update |
| `repo/deploy/.env` | Compose project name, `OEDS_RUNTIME_DIR`, service passwords and port overrides (written by Ansible) |
| `runtime/CRAWLER_CONFIG.yml` | Crawler settings, enable switches, schedules and `default.max_parallel_runs`; seeded from `deploy/CRAWLER_CONFIG.yml` on the first install |
| `runtime/crawler/.env` | Source API keys; never commit this file |
| `runtime/crawler/data/` | Downloads and crawler working files |
| `runtime/logs/`, `runtime/crawler_admin_state/` | Logs (`logs/runs/` has one file per scheduled run) and admin run history |

Persistent data lives on the data partition (`oeds_data_root`, default `/home`):

| Path | Purpose |
| --- | --- |
| `/home/oeds/docker_data/` | Persistent PostgreSQL, Grafana and pgAdmin data |
| `/home/oeds/backups/<timestamp>/` | Database dumps taken on request (`--backup`) before an update; the newest three are kept |

The Compose definition is `repo/deploy/compose.yml`. Docker uses its built-in
volume driver for new installations; existing volumes are not replaced on update.

## Develop locally

```bash
uv sync --all-packages --all-extras            # repository root
uv run pytest deploy/tests
uv run python deploy/tools/verify_deployment.py
docker build -f deploy/docker/Dockerfile.crawler-modular --target runtime -t oeds-runtime:dev .
```

For container commands, change to `deploy/` first (`docker compose --profile
crawlers -f compose.yml ...` with `OEDS_RUNTIME_DIR` pointing at a runtime
directory); for Ansible, use `deploy/playbooks`. Historical migration reports
are kept in Git history.

## Dashboards and tests

[Grafana setup](data/provisioning/grafana/README.md) explains the two starter
dashboards and optional source/research dashboards. No crawler implementation
or specialist dashboard was removed by the deployment simplification.
The small integration suite tests actual data writes and SQL panel queries;
it is not a claim that every external API or research dashboard is available.
See [the latest VM results and known limits](docs/test-results.md).
