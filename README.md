# oeds-deployment

Installation and operations entry point for modular OEDS.

This repository assembles the original
[Open Energy Data Server](https://github.com/open-energy-data-server/open-energy-data-server)
with the compatible revisions of these add-ons:

| Repository | Responsibility |
| --- | --- |
| `oeds-crawler-pack` | KIT crawler implementations and temporary BaseCrawler compatibility |
| `oeds-scheduler-ui` | scheduler, crawler runtime, and admin UI |
| `oeds-post-scripts` | gapfill, backfill, forecasts, and derived-data jobs |
| `oeds-deployment` | Compose, Ansible, provisioning, installation, and compatibility pins |

There is no separate distribution repository. This repository owns assembly
and installation. `compatibility.yml` is the single list of compatible source
revisions. `open-energy-data-server-KIT` is not needed at runtime or during
installation.

## Fastest Linux Install

Requirements:

- Linux host with `sudo`
- Python 3 and Git
- network access to GitHub and container registries
- GitHub token with read access while the add-on repositories are private
- optional crawler `.env` containing credentials for token-backed sources

Clone this repository, then run the installer:

```bash
git clone https://github.com/johannesschuhmacher/oeds-deployment.git
cd oeds-deployment

export OEDS_GIT_USERNAME='<github-user>'
read -rsp 'GitHub token: ' OEDS_GIT_TOKEN
export OEDS_GIT_TOKEN

bash ./tools/oeds_clean_install_from_git.sh \
  --reset \
  --crawler-env-file /path/to/crawler.env \
  --load-sample-data \
  --include-entsoe-fms
```

Remove `--reset` to preserve the existing database and runtime directory.
Remove `--load-sample-data` for a normal installation without immediate live
crawler runs. The token is passed to Git through a temporary `GIT_ASKPASS`
helper and is not written into the assembled workspace.

When `sudo` cannot prompt interactively, point the installer at a local file:

```bash
export OEDS_BECOME_PASSWORD_FILE=/path/to/sudo-password-file
```

Keep token, password, and crawler environment files outside every checkout.

## Manual Assembly

The assembler uses only Python's standard library. It clones the exact commits
from `compatibility.yml` and creates the workspace expected by Docker and
Ansible.

Linux:

```bash
python3 tools/assemble_workspace.py --output "$HOME/oeds-assembled" --clean
```

PowerShell:

```powershell
python .\tools\assemble_workspace.py --output C:\tmp\oeds-assembled --clean
```

Resulting structure:

```text
oeds-assembled/
  CRAWLER_CONFIG.yml
  crawler/
    .env.example
    data/
  modular_repos/
    sources/oeds-core/
    modules/oeds-crawler-pack/
    modules/oeds-scheduler-ui/
    modules/oeds-post-scripts/
    modules/oeds-deployment/
```

The workspace deliberately contains no checkout of
`open-energy-data-server-KIT` and no copied root Python environment.

## Docker Compose

Run Compose from the deployment module inside the assembled workspace:

```bash
cd "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment"
docker compose --profile crawlers -f compose.yml up -d --build
```

`compose.yml` is the primary modular definition. `compose.modular.yml` remains
compatible with existing two-file commands during the transition:

```bash
docker compose --profile crawlers \
  -f compose.yml -f compose.modular.yml up -d --build
```

Without `OEDS_RUNTIME_DIR`, mutable files are read from the assembled workspace
root. Set it to an absolute path for managed installations. It must contain:

```text
CRAWLER_CONFIG.yml
crawler/.env
crawler/data/
logs/
crawler_admin_state/
```

The scheduler container runs as the non-root `oeds` image user. The admin UI
currently runs as root inside its container because it must update the
root-owned bind-mounted `CRAWLER_CONFIG.yml` created by Ansible. The admin UI
should not be exposed to untrusted networks without an authentication layer.

Managed installations store crawler secrets as `root:docker` with mode `0640`.
The Compose `.env` files contain only the project name and runtime path and use
mode `0644`. A host operator therefore needs membership in the `docker` group
to read crawler secrets and manage the stack without `sudo`.

## Ansible

For a preassembled local workspace:

```bash
cd /path/to/oeds-assembled/modular_repos/modules/oeds-deployment/playbooks
ansible-galaxy collection install -r requirements.yml
cp inventory.example.yml inventory.yml

ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml \
  oeds-install-crawlers.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src=/path/to/oeds-assembled
```

The defaults install to:

```text
/open_energy_data_server/repo
/open_energy_data_server/runtime
/open_energy_data_server/docker_data
/open_energy_data_server/backups
```

In `git` source mode the playbooks clone `oeds-deployment` into
`/open_energy_data_server/deployment-source` and run the same assembler before
starting Compose. This mode is suitable once the repositories are public or
Git access is already configured on the target host. During private testing,
use `oeds_clean_install_from_git.sh` so one temporary token covers all clones.

Update an existing installation:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-update.yml
```

The uninstall defaults preserve data. A destructive reset requires all three
explicit flags and the confirmation value:

```bash
ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i inventory.yml oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true \
  -e oeds_uninstall_remove_runtime=true \
  -e oeds_uninstall_destroy_data=true \
  -e oeds_uninstall_confirm=DELETE_OEDS_DATA
```

## Verification

Static checks:

```bash
python3 tools/verify_deployment.py --local-only
python3 /path/to/oeds-assembled/modular_repos/tools/verify_modules.py
docker compose --profile crawlers -f compose.yml config --quiet
```

Disposable integration checks from the assembled deployment module:

```bash
sudo bash ./tools/test_db_smoke.sh
sudo bash ./tools/test_real_crawler_smoke.sh --run-post-scripts
sudo bash ./tools/test_active_crawlers_smoke.sh --include-entsoe-fms
sudo bash ./tools/test_stack_smoke.sh
```

Load a bounded sample into the installed normal database:

```bash
sudo bash ./tools/load_sample_data.sh --include-entsoe-fms
```

## Core Boundary

The official OEDS repository remains the base and is never replaced by this
deployment. Generic improvements to the crawler contract, BaseCrawler, or
database handling should be proposed upstream. Until those changes are merged,
the adapter required by the KIT crawlers lives in `oeds-crawler-pack`.

Scheduler/UI, post-processing, and deployment behavior stay in their own
repositories and are not candidates for the OEDS core merge.

## Publication Boundary

Do not publish `.env` files, tokens, password files, runtime state, logs,
database volumes, dumps containing real data, or machine-specific files. The
repositories may publish source, tests, example configuration, Compose,
Ansible, provisioning assets, and documentation.
