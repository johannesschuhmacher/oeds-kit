# Modular OEDS

Start here to install OEDS. You do not need to install the repositories by hand.

| Repository | What it does |
| --- | --- |
| [Official OEDS](https://github.com/open-energy-data-server/open-energy-data-server) | Upstream crawler and database library; current tests use the private [core test branch](https://github.com/johannesschuhmacher/oeds-core) with fixes intended for upstream review |
| [Crawler pack](https://github.com/johannesschuhmacher/oeds-crawler-pack) | Our enhanced/new crawlers and temporary BaseCrawler compatibility |
| [Scheduler/UI](https://github.com/johannesschuhmacher/oeds-scheduler-ui) | Scheduled jobs, post-run commands and browser administration |
| [Post-scripts](https://github.com/johannesschuhmacher/oeds-post-scripts) | Gapfilling, backfill, forecasts and derived database views |
| This repository | Installation, Docker Compose, Ansible and Grafana provisioning |

There is no separate distribution module. `compatibility.yml` lists compatible
Git revisions. Assembly checks out those revisions; it does not copy the KIT
monorepository. Shared crawler improvements can later be contributed upstream.
The test core retains upstream history and licensing. It is not an official
OEDS release; `compatibility.yml` identifies the exact tested revision.

## Install on a Linux VM

Run these commands **inside the VM's Linux terminal**, after connecting with
SSH from Windows. Automated host preparation currently targets CentOS Stream;
Ubuntu host preparation has not been validated. You need Git, Python 3.12+,
sudo access and network access to GitHub/container registries.

While the repositories are private, the initial HTTPS clone needs Git read
access. Use your credential helper, or enter your GitHub username and a read
token when Git asks for a password. Do not put a token in a clone URL or a
committed file. The installer uses a temporary credential helper for its clones.

```bash
git clone https://github.com/johannesschuhmacher/oeds-deployment.git
cd oeds-deployment
read -rsp 'GitHub read token: ' OEDS_GIT_TOKEN; echo
export OEDS_GIT_TOKEN
bash tools/oeds_clean_install_from_git.sh --crawler-env-file "$HOME/crawler.env"
unset OEDS_GIT_TOKEN
```

The environment file is optional; omit that option for sources without API
keys. The installer asks for your sudo password. Existing database and runtime
settings are preserved. **Do not add `--reset` unless you intend to delete
the old database and runtime settings.** All crawlers start disabled: choose
the sources you need in the admin UI before enabling a schedule.

For a guided, module-by-module installation and test, follow
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
| `repo/` | Installed source code; replaced by an update |
| `runtime/CRAWLER_CONFIG.yml` | Crawler settings, enable switches and schedules |
| `runtime/crawler/.env` | Source API keys; never commit this file |
| `runtime/crawler/data/` | Downloads and crawler working files |
| `runtime/logs/`, `runtime/crawler_admin_state/` | Logs and admin run history |
| `docker_data/` | Persistent PostgreSQL, Grafana and pgAdmin data |
| `backups/` | Private backups |

One Compose definition lives at `repo/modular_repos/modules/oeds-deployment/compose.yml`.
The old `compose.modular.yml` is an empty compatibility file, not a second
configuration to maintain. Docker uses its built-in volume driver for new
installations; existing volumes are not replaced on update.

## Develop locally

```bash
python3 tools/assemble_workspace.py --output "$HOME/oeds-assembled"
python3 -m unittest discover -s tests -v
python3 tools/verify_deployment.py --local-only
```

The assembler needs only Python's standard library. `--dry-run` prints the
plan without changing files. `--clean` explicitly replaces an existing output
directory. Never put output inside the deployment checkout.

Each module has its own README and focused tests. For container commands,
change to `oeds-assembled/modular_repos/modules/oeds-deployment` first. For
Ansible, use its `playbooks` directory. Historical migration reports are kept
in Git history, not copied into every assembled installation.

## Dashboards and tests

[Grafana setup](data/provisioning/grafana/README.md) explains the two starter
dashboards and optional source/research dashboards. No crawler implementation
or specialist dashboard was removed by the deployment simplification.
The small integration suite tests actual data writes and SQL panel queries;
it is not a claim that every external API or research dashboard is available.
See [the latest VM results and known limits](docs/test-results.md).
