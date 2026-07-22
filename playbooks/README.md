# OEDS Ansible Playbooks

These playbooks are the public installation and operations path for OEDS.
They cover generic host preparation, installation, updates, backups, database
migration, rollback, smoke tests, and uninstall workflows.

Secrets, inventories, host-specific overrides, and runtime data do not belong
in the repository. Keep them in local `group_vars`, untracked `.env` files, or
host-side runtime directories.

For managed internal deployments, keep the repo-root compose `.env` at `0600`.
It is the natural place for the rotated OEDS service passwords because Compose
loads it automatically.

## Quick install

Use these playbooks on a Linux target host. The recommended and currently
supported server family is CentOS/RHEL-compatible Linux with `dnf`, for example
CentOS Stream, Rocky Linux, AlmaLinux, or RHEL.

You need a sudo-capable user, Ansible on the control node, and the collections
from `requirements.yml`. If Docker is not installed yet on a supported target,
run `oeds-install-host-prep.yml` before the install playbook.

Use this path for a simple same-host install with the core services, scheduler,
and crawler admin UI:

```bash
cd playbooks
ansible-galaxy collection install -r requirements.yml
cp inventory.example.yml inventory.yml
ansible -i inventory.yml oeds -m ping
ansible-playbook -i inventory.yml oeds-install-host-prep.yml
ansible-playbook -i inventory.yml oeds-install-crawlers.yml
ansible-playbook -i inventory.yml oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

If Docker is already installed and working, `oeds-install-host-prep.yml` can be
skipped.

The install wrapper already runs the smoke test once. Running
`oeds-smoke-test.yml` again is useful when you want an explicit final check.

For a remote host, edit `inventory.yml`: replace `localhost` with the host's
`ansible_host` and set `ansible_user` if needed. Keep `group_vars/oeds.yml`
absent unless you really need local overrides.

## Simplified GitLab VM install

For the modular private GitLab split, use the wrapper from the deployment
repository when a fresh Linux VM should clone everything directly from GitLab:

```bash
export OEDS_GIT_USERNAME=oauth2
export OEDS_GIT_TOKEN='<gitlab-token>'

git clone https://gitlab.kit.edu/kit/iip/energyeconomics/sem-fec/josc/oeds-deployment.git
cd oeds-deployment
bash ./tools/oeds_clean_install_from_git.sh \
  --reset \
  --load-sample-data \
  --include-entsoe-fms
```

Use `OEDS_GIT_USERNAME=oauth2` for a personal access token. For a GitLab deploy
token, use the deploy-token username. The wrapper clones `oeds-deployment`,
assembles all compatible component repositories from `compatibility.yml`, runs
host prep unless `--skip-host-prep` is passed, optionally performs a destructive
reset, installs the modular stack, runs the Ansible smoke test, and can load a
bounded real-data sample into the installed database.

For unattended sudo, pass a local password file:

```bash
export OEDS_BECOME_PASSWORD_FILE=/path/to/sudo-password-file
```

Keep GitLab tokens and sudo password files outside the repository.

Use the default `git` source mode when the target host can clone the selected
branch, tag, or commit itself. Use `local_archive` when you need to deploy a
committed local checkout that the target host cannot clone:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_source_mode=local_archive \
  -e oeds_repo_local_src=/home/oeds/open-energy-data-server \
  -e oeds_repo_version=HEAD
```

In `local_archive` mode, Ansible creates a `git archive` on the control node
and transfers that archive to the target host. `oeds_repo_local_src` is the
checkout path on the machine running Ansible. `oeds_repo_version` is the branch,
tag, commit, or `HEAD` to package. Only committed, tracked files from that ref
are included.

For testing unpublished, uncommitted local changes, use `local_worktree`:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src=/home/oeds/oeds-vm-test-export \
  -e oeds_enable_crawlers=true
```

`local_worktree` packages the current files from `oeds_repo_local_src`,
including uncommitted and untracked files, while excluding VCS metadata, caches,
logs, runtime directories, and Docker data. Use it for internal VM validation,
not for public release artifacts.

## Target layout

The playbooks install and operate OEDS on a Linux host with Docker Compose.
The Compose file stays in the repository checkout, while mutable runtime data
is stored outside the checkout.

Default target paths:

```text
/open_energy_data_server/repo          # OEDS repository checkout
/open_energy_data_server/docker_data   # persistent Docker volume data
/open_energy_data_server/runtime       # config, secrets, logs, admin state
/open_energy_data_server/backups       # backup and migration artifacts
```

Runtime extraction means that `CRAWLER_CONFIG.yml`, `crawler/.env`,
`crawler/data`, `logs`, and `crawler_admin_state` are stored outside the git
checkout. This allows repo updates or fresh checkouts without overwriting local
configuration, secrets, logs, or admin state.

The public playbooks still bootstrap the same intentionally insecure fallback
service passwords as the public `compose.yml`. That is acceptable for isolated
local, internal, or disposable test systems, but not for shared or public
hosts.

Crawler containers read `crawler/.env` via Compose `env_file`. The file must
exist on the host, but it is not mounted into the container as a readable bind
mount.

Recommended split between public repo content and private operations data:

- Keep the versioned `CRAWLER_CONFIG.yml` generic and free of personal email
  recipients, production SMTP hosts, or credentials.
- Store real email recipients, SMTP credentials, and crawler secrets only in
  untracked files such as `crawler/.env`, host runtime `.env`, or
  `group_vars/oeds.yml`.
- Use `OEDS_EMAIL_TOADDRS`, `OEDS_EMAIL_MAILHOST`, `OEDS_EMAIL_FROMADDR`,
  `OEDS_EMAIL_USERNAME`, and `OEDS_EMAIL_PASSWORD` to override mail settings
  locally without editing the versioned YAML.

## Requirements

Control node:

- Linux or WSL is recommended. Ansible is not a good native Windows control
  node.
- SSH access as a sudo-capable user.
- For installs on the same Linux host, `inventory.example.yml` already uses
  `ansible_connection: local` with `sudo`.
- `ansible` plus the collections from `requirements.yml`.

Install control-node dependencies:

```bash
uv tool install --with ansible-lint ansible
ansible-galaxy collection install -r requirements.yml
```

If you use WSL, clone the repository into the Linux filesystem when possible
instead of `/mnt/c/...`. In world-writable mounts Ansible ignores `ansible.cfg`.
If you still work from `/mnt/c/...`, always pass `-i inventory.yml` explicitly.
For playbook status mail support, load `ansible.cfg` explicitly:

```bash
ANSIBLE_CONFIG=playbooks/ansible.cfg ansible-playbook -i playbooks/inventory.yml playbooks/oeds-smoke-test.yml
```

Target host:

- A RHEL, Rocky, Alma, or CentOS compatible system with `dnf`.
- Python for Ansible modules.
- Network access to Docker registries and the selected git remote.
- Enough storage for PostgreSQL data and backups.

## Inventory and local variables

Create a local inventory:

```bash
cp inventory.example.yml inventory.yml
ansible -i inventory.yml oeds -m ping
```

`inventory.example.yml` is ready for the simplest public case: install OEDS on
the same Linux host where you run Ansible, with `sudo`, from the public GitHub
`main` branch.

For a remote host, replace the `localhost` entry with `ansible_host` and, when
needed, `ansible_user`.

Optional local overrides:

```bash
mkdir -p group_vars
cp group_vars/oeds.example.yml group_vars/oeds.yml
```

You do not need `group_vars/oeds.yml` for the public default rollout.
`group_vars/oeds.yml` is only for local host configuration overrides such as a
different git remote, branch/tag/commit, or custom target directories, and it
should stay unversioned.

## Repository access and private rollouts

In the default `git` mode, the target host must be able to reach
`oeds_repo_url` on its own. For unpublished branches or commits, there are
three useful options:

- Give the host git access with a deploy key or token.
- Point the playbooks to an internal mirror the host can read.
- Use `oeds_repo_source_mode=local_archive` to build a local `git archive` on
  the control node and unpack it on the target host.
- Use `oeds_repo_source_mode=local_worktree` to package the current local file
  tree, including uncommitted/untracked files, for an internal test rollout.

Example with a host-local mirror:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_url=/open_energy_data_server/backups/oeds.git \
  -e oeds_repo_version=<commit>
```

All public playbooks honor overrides from `group_vars/oeds.yml` or `-e` for:

- `oeds_repo_url`
- `oeds_repo_version`
- `oeds_root`
- `oeds_runtime_dir`
- `oeds_data_dir`

Example local-archive rollout:

```bash
ansible-playbook -i inventory.yml oeds-update.yml \
  -e oeds_repo_source_mode=local_archive \
  -e oeds_repo_local_src=/path/to/oeds \
  -e oeds_repo_version=main \
  -e oeds_enable_crawlers=true
```

`local_archive` packages the selected git ref, not arbitrary working-tree
state. For a current local checkout, pass `-e oeds_repo_version=HEAD` or a
specific commit and make sure all required changes are committed. Uncommitted
and untracked files are not included in the archive.

Example local-worktree rollout:

```bash
ansible-playbook -i inventory.yml oeds-update.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src=/path/to/oeds \
  -e oeds_enable_crawlers=true
```

Use `local_worktree` for fresh checkout tests before commits or publication.
Review `git status --short` before running it so accidental local files are not
deployed.

In `git` mode, the playbooks verify repo access before any downtime step with
`GIT_TERMINAL_PROMPT=0`. Missing credentials fail fast instead of hanging in a
blocked `git fetch`.

## Playbook status emails

The public playbooks ship an Ansible callback plugin named `oeds_mail`. When
`ansible.cfg` is loaded and SMTP sender, recipient, and host are configured,
the callback sends one status email at the end of each playbook run.

- Successful runs are reported as `SUCCESS`.
- Runtime failures and unreachable hosts are reported as `FAILED`.
- Syntax errors that happen before callback plugins are loaded cannot trigger
  emails.
- Repeated identical status emails are rate-limited by default to one message
  per hour. Set `OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS=0` to disable this, or
  use `OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES` for a different cooldown.

The callback can use the same local mail overrides as the crawler runtime:

```bash
export OEDS_EMAIL_MAILHOST=smtp.example.com:25
export OEDS_EMAIL_FROMADDR=oeds@example.com
export OEDS_EMAIL_TOADDRS=person1@example.com,person2@example.com
```

Dedicated Ansible mail variables take precedence:

```bash
export OEDS_ANSIBLE_EMAIL_MAILHOST=smtp.example.com:587
export OEDS_ANSIBLE_EMAIL_FROMADDR=oeds-ansible@example.com
export OEDS_ANSIBLE_EMAIL_TOADDRS=ops@example.com
export OEDS_ANSIBLE_EMAIL_STARTTLS=true
export OEDS_ANSIBLE_EMAIL_USERNAME=smtp-user
export OEDS_ANSIBLE_EMAIL_PASSWORD='...'
export OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES=60
```

If `crawler/.env` exists on the control node, it is used as a fallback source
for `OEDS_EMAIL_*`. Keep secrets in local environment variables or untracked
`.env` files, never in the repository.

The rate-limit state is stored in the control user's cache directory by
default. Override it with `OEDS_ANSIBLE_EMAIL_RATE_LIMIT_STATE_FILE` if the
control environment should persist it elsewhere.

## Internal password rotation

For internal long-running hosts, use the host-side rotation script instead of
manually editing passwords:

```bash
export BW_SERVER_URL=https://bitwarden.example.internal
export BW_CLIENTID=...
export BW_CLIENTSECRET=...
export BW_PASSWORD=...
python scripts/rotate_oeds_passwords.py --deployment-name intern-test
```

The script:

- generates fresh passwords for `opendata`, `readonly`, the Grafana admin, and
  the pgAdmin admin,
- updates the live OEDS containers,
- rewrites the repo-root Compose `.env` with the new secret values,
- restarts the affected services,
- and upserts the credentials into Bitwarden under `OEDS/<deployment-name>`.

Bitwarden-specific notes:

- The script uses the official `bw` CLI because Bitwarden documents vault-item
  automation through the Vault Management path exposed by the CLI.
- `BW_CLIENTID` and `BW_CLIENTSECRET` authenticate `bw login --apikey`.
- `BW_PASSWORD` is still required because Bitwarden requires an explicit
  `unlock` step before vault items can be read or edited.

Operational notes:

- Run the script on the target OEDS host, usually as the same privileged user
  that owns the deployment checkout and Docker access.
- A timestamped backup of the previous `.env` is kept next to the file.
- On failure, the script attempts to roll the passwords back and leaves a local
  pending-secret file for manual recovery if rollback is incomplete.

### Run it centrally across one or more VMs

If you already manage your OEDS hosts through the Ansible inventory, use the
dedicated rotation playbook instead of SSHing into every VM:

```bash
export BW_SERVER_URL=https://bitwarden.example.internal
export BW_CLIENTID=...
export BW_CLIENTSECRET=...
export BW_PASSWORD=...
ANSIBLE_CONFIG=playbooks/ansible.cfg \
ansible-playbook -i playbooks/inventory.yml playbooks/oeds-rotate-passwords.yml
```

The playbook runs `serial: 1`, so the hosts rotate one after another instead
of all at once.

To rotate only selected hosts:

```bash
ANSIBLE_CONFIG=playbooks/ansible.cfg \
ansible-playbook -i playbooks/inventory.yml playbooks/oeds-rotate-passwords.yml \
  -l intern-test,extern
```

To inspect the plan without changing anything:

```bash
ANSIBLE_CONFIG=playbooks/ansible.cfg \
ansible-playbook -i playbooks/inventory.yml playbooks/oeds-rotate-passwords.yml \
  -e oeds_rotation_dry_run=true
```

Useful per-host inventory or `group_vars` overrides:

- `oeds_rotation_deployment_name`: label used in Bitwarden item names
- `oeds_rotation_access_host`: URI host written into Bitwarden entries
- `oeds_rotation_bitwarden_folder`: folder override, default `OEDS/<deployment-name>`
- `oeds_rotation_password_length`: generated password length, default `32`

Example inventory excerpt:

```yaml
all:
  children:
    oeds:
      hosts:
        intern-test:
          ansible_host: iip-vm-oeds-intern-test.iip.kit.edu
          ansible_user: your-ssh-user
          ansible_become: true
          oeds_rotation_deployment_name: intern-test
          oeds_rotation_access_host: iip-vm-oeds-intern-test.iip.kit.edu
        extern:
          ansible_host: iip-vm-oeds-extern.iip.kit.edu
          ansible_user: your-ssh-user
          ansible_become: true
          oeds_rotation_deployment_name: extern
          oeds_rotation_access_host: iip-vm-oeds-extern.iip.kit.edu
```

Dry-run example:

```bash
ANSIBLE_CONFIG=playbooks/ansible.cfg \
OEDS_ANSIBLE_EMAIL_DRY_RUN=true \
OEDS_ANSIBLE_EMAIL_DRY_RUN_FILE=/tmp/oeds-ansible-status.eml \
OEDS_ANSIBLE_EMAIL_MAILHOST=localhost \
OEDS_ANSIBLE_EMAIL_FROMADDR=oeds@example.com \
OEDS_ANSIBLE_EMAIL_TOADDRS=ops@example.com \
ansible-playbook -i playbooks/inventory.yml playbooks/oeds-smoke-test.yml
```

## Installation options

The public entry points are wrapper playbooks that call the lower-level tasks
in the correct order.

### Option 1: Local developer start

Without Ansible, directly from the repository:

```bash
docker compose up -d
```

This quick-start path uses intentionally insecure fallback credentials from the
public repository and is only suitable for isolated local, internal, or
disposable test systems.

With crawler containers:

```bash
docker compose --profile crawlers up -d --build
```

This is the fastest path for local testing, but not a full server setup.

### Option 2: Prepare a new host

Install OS repositories, a generic SELinux policy adjustment, and Docker
packages:

```bash
ansible-playbook -i inventory.yml oeds-install-host-prep.yml
```

Use this on a fresh Linux host. If Docker is already installed and working, you
can skip this step.

### Option 3: Install OEDS core services

Install packages, Docker volumes, runtime directories, the repo checkout, and
start PostgreSQL, PostgREST, Grafana, and PgAdmin:

```bash
ansible-playbook -i inventory.yml oeds-install-core.yml \
  -e oeds_repo_version=<branch-tag-or-commit>
```

This is the recommended minimal path for a server without the scheduler and
without the crawler admin UI.

If the target host is not a throwaway internal test system, set
`OEDS_DB_PASSWORD`, `OEDS_READONLY_PASSWORD`, `OEDS_GRAFANA_ADMIN_PASSWORD`,
and `OEDS_PGADMIN_DEFAULT_PASSWORD` before the first startup.

### Option 4: Install OEDS with crawler services

Install the core stack plus the scheduler and crawler admin UI containers:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_version=<branch-tag-or-commit>
```

This is the recommended default path for a long-running OEDS instance. The
selected `oeds_repo_version` must include the `crawlers` compose profile.

For the public default install from GitHub `main`, no extra variables are
required:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml
```

That public default install remains intentionally insecure and is only meant
for internal or disposable test hosts unless you override the service
passwords before first startup.

Example first run on a clean test VM:

```bash
ansible -i inventory.yml oeds -m ping
ansible-playbook -i inventory.yml oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true \
  -e oeds_uninstall_remove_runtime=true \
  -e oeds_uninstall_destroy_data=true \
  -e oeds_uninstall_confirm=DELETE_OEDS_DATA
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_version=<commit>
ansible-playbook -i inventory.yml oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

For a same-host validation of an unpublished local checkout, keep the inventory
explicit and use `local_worktree` for uncommitted local test state. The
uninstall playbook does not need repository source overrides; its conservative
defaults stop and remove containers and networks while keeping data, images,
runtime files, and backups.

```bash
ansible -i inventory.yml oeds -m ping
ansible-playbook -i inventory.yml oeds-uninstall.yml
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src=/home/oeds/open-energy-data-server
```

A clean install is not a fully populated OEDS instance. Crawler-dependent
schemas and dashboards only become useful after the first successful crawler
run. The validation flow therefore includes at least one manual
`weather_forecast` run through the crawler admin UI.

For production, `oeds_repo_version` should point to a tested branch, tag, or
commit, not a floating `latest`.

## Update workflow

Use this playbook for normal application, Compose, and container-image updates:

```bash
ansible-playbook -i inventory.yml oeds-update.yml \
  -e oeds_repo_version=<branch-tag-or-commit> \
  -e oeds_enable_crawlers=true
```

If the instance uses the crawler profile and stays on the public GitHub
defaults, the simpler wrapper is:

```bash
ansible-playbook -i inventory.yml oeds-update-crawlers.yml
```

The update playbook:

- creates a logical database backup if the DB is running,
- stops legacy Compose projects,
- checks out the requested repo version,
- writes `.env` with `OEDS_RUNTIME_DIR`,
- refreshes Grafana, PgAdmin, and SQL provisioning from the repo,
- runs `docker compose pull` and `docker compose up -d`,
- blocks accidental PostgreSQL major upgrades.

Optional OS package updates:

```bash
ansible-playbook -i inventory.yml oeds-update.yml \
  -e oeds_update_docker_packages=true
```

Set these flags deliberately rather than leaving them enabled by default.

## PostgreSQL and TimescaleDB migration

A PostgreSQL major upgrade must not happen just by swapping the image. Use the
dedicated migration playbook.

1. Create a backup:

```bash
ansible-playbook -i inventory.yml oeds-db-backup.yml
```

2. Restore into staging first:

```bash
ansible-playbook -i inventory.yml oeds-db-migrate.yml \
  -e oeds_apply_cutover=false
```

3. Validate the staging result, review logs, and run smoke tests.

4. Apply cutover only after validation:

```bash
ansible-playbook -i inventory.yml oeds-db-migrate.yml \
  -e oeds_apply_cutover=true \
  -e oeds_enable_crawlers_after_cutover=true
```

5. Run the smoke test:

```bash
ansible-playbook -i inventory.yml oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

## Rollback

Rollback expects an older PostgreSQL data directory, for example from a
migration backup:

```bash
ansible-playbook -i inventory.yml oeds-db-rollback.yml \
  -e oeds_rollback_source_dir=/open_energy_data_server/backups/<run-id>/postgres-home-pre-cutover \
  -e oeds_enable_crawlers_after_rollback=true
```

## Uninstall and test reset

Conservative uninstall without deleting data:

```bash
ansible-playbook -i inventory.yml oeds-uninstall.yml
```

This removes containers and Docker networks but keeps the repo checkout,
runtime files, backups, and Docker volumes. Docker itself and generic
host-level OS settings are not removed.

Fresh test run with a new repo checkout:

```bash
ansible-playbook -i inventory.yml oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true
```

Full test-VM reset including database volumes, runtime config, and repo:

```bash
ansible-playbook -i inventory.yml oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true \
  -e oeds_uninstall_remove_runtime=true \
  -e oeds_uninstall_destroy_data=true \
  -e oeds_uninstall_confirm=DELETE_OEDS_DATA
```

To remove backups and cached Docker images as well:

```bash
ansible-playbook -i inventory.yml oeds-uninstall.yml \
  -e oeds_uninstall_remove_repo=true \
  -e oeds_uninstall_remove_runtime=true \
  -e oeds_uninstall_destroy_data=true \
  -e oeds_uninstall_remove_backups=true \
  -e oeds_uninstall_remove_images=true \
  -e oeds_uninstall_confirm=DELETE_OEDS_DATA
```

After that, rebuild the VM with one of the installation levels, for example:

```bash
ansible-playbook -i inventory.yml oeds-install-crawlers.yml \
  -e oeds_repo_version=<branch-tag-or-commit>
```

## Playbook reference

- `oeds-install-host-prep.yml`: prepare a new host with packages and OS-level
  dependencies.
- `oeds-install-core.yml`: install the OEDS core stack without crawler
  services.
- `oeds-install-crawlers.yml`: install the core stack plus scheduler and
  crawler admin UI.
- `oeds-packages.yml`: install Docker/Compose packages.
- `oeds-docker-config.yml`: initialize Docker volumes, runtime directories,
  the repo checkout, and the Compose stack.
- `oeds-update.yml`: roll out a new repo, Compose, or image version.
- `oeds-db-backup.yml`: create database, extension, Compose, and runtime
  backups.
- `oeds-db-migrate.yml`: migrate PostgreSQL/TimescaleDB via dump/restore into
  a new target container and optionally apply cutover.
- `oeds-db-rollback.yml`: restore the live PostgreSQL data path from an older
  data snapshot.
- `oeds-uninstall.yml`: stop and remove OEDS containers and networks; delete
  data, runtime, repo, backups, or images only when explicitly requested.
- `oeds-smoke-test.yml`: verify PostgreSQL, PostgREST, Grafana, PgAdmin, and
  optionally the crawler admin UI. HTTP endpoints are checked with retries to
  avoid false alarms on fresh startups.

Reverse proxy, TLS, firewall customization, and other institution-specific edge
integration are intentionally not part of the public default path and should be
maintained outside this repository.

## Repository boundary

The public playbooks belong in the repository as long as this boundary is kept:

- Generic install, update, backup, migration, rollback, and smoke-test logic
  may stay in the repo.
- `inventory.yml`, `group_vars/oeds.yml`, secrets, and runtime data remain
  private.
- Internal institution-specific deployment playbooks belong in private ops
  overlays, not in the public branch.
- Updates should use tested tags, branches, or commits, not uncontrolled
  floating versions.
