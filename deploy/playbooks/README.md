# Operations

For a first installation, use the [main README](../README.md). For a clean VM
test, follow [the step-by-step test guide](../docs/testing.md).

Run the commands below from this directory on the Linux VM. `-K` asks for
the sudo password. Use `inventory.local.yml` on the VM itself, or copy
`inventory.example.yml` for remote hosts. Change `ansible_user` to your user.

```bash
export ANSIBLE_CONFIG=ansible.cfg
ansible-galaxy collection install -r requirements.yml
ansible -i inventory.local.yml oeds -m ping
```

The defaults of all playbooks, with comments, are in `group_vars/all.yml`. To
change one for a host, set it in `group_vars/oeds.yml` (ignored by Git), as a
host variable in the inventory or with `-e`. Group `vars:` inside the
inventory file rank below `group_vars/all.yml` and have no effect.

The automated host preparation targets CentOS Stream and currently sets SELinux
to permissive mode. Review this host-wide security change with your administrator.
Ubuntu host setup has not been verified. Docker access grants host-level control;
only trusted operators should join the `docker` group.

## Update without losing settings

Check out the new revision of oeds-kit outside the installed `repo/` directory
first (for example `$HOME/oeds-kit`). For private forks, use your Git
credential helper or the installer's temporary `GIT_ASKPASS` token mechanism.
Never embed credentials in clone URLs.

```bash
ansible-playbook -i inventory.local.yml -K oeds-install-crawlers.yml \
  -e oeds_repo_local_src="$HOME/oeds-kit"
```

Install and update are the same run of `oeds-deploy.yml`, which
`oeds-install-crawlers.yml` imports together with the smoke test and the
post-processing SQL. Re-running the installer does the same. The source is
the checkout at `oeds_repo_local_src` on the control node, copied as it is
(including uncommitted changes, without `.git`).

1. The new source is unpacked to `repo.next/` and the crawler images are built
   and the service images pulled there, while the running services continue.
   If the build fails, the build cache is cleared and the build repeated once;
   a second failure stops the update with the old services still running.
2. With `-e oeds_backup_before_update=true` (installer: `--backup`) the
   database is dumped (`pg_dump -Fc` plus the globals) into
   `/home/oeds/backups/<timestamp>/` (`oeds_backup_dir`); only the newest
   `oeds_backup_keep` (default 3) directories are kept. The dump is off by
   default because it takes over 30 minutes for a 140-GB database and an
   update does not change the database.
3. The update waits up to `oeds_update_wait_for_crawls_minutes` (default 15)
   for running crawls, then moves `repo/` to `repo.prev/` and `repo.next/`
   to `repo/`.
4. `docker compose up -d --remove-orphans` replaces only the containers whose
   image or settings changed; Grafana and pgAdmin are recreated because they
   mount files from `repo/`. PostgreSQL keeps running unless its image changed.
   `repo.prev/` is removed afterwards.

Crawler settings, Compose passwords/ports and Docker volumes are preserved.
`-e oeds_package_state=latest` also updates the Docker packages; normal runs
leave them alone. PostgreSQL major version changes require a separate
migration (`oeds-db-migrate.yml`), not an ordinary update.

The crawler image installs exactly the root `uv.lock` (`uv sync --frozen`).
When a package changes its dependencies or the `oeds` revision in the root
`pyproject.toml` moves, run `uv lock` and commit the lock in the same change.

## Backup and restore

```bash
ansible-playbook -i inventory.local.yml -K oeds-db-backup.yml
ansible-playbook -i inventory.local.yml -K oeds-db-migrate.yml \
  -e oeds_apply_cutover=false
```

The first command stores a private logical backup and runtime settings under
`/home/oeds/backups/<timestamp>` (`oeds_backup_dir`), the same directory the
update backups use, so it is subject to the same `oeds_backup_keep` pruning.
The second restores into a separate staging database on port 6543. Compare
row counts and query results before continuing.
The port is bound to localhost. The target bootstrap administrator must match
the source bootstrap role (normally `opendata`); role ownership and grants are
restored from the private globals dump.

For an approved migration, rerun with `oeds_apply_cutover=true` and
`oeds_enable_crawlers_after_cutover=true`. The old database directory is retained
under the backup path printed by Ansible. Cutover stops the scheduler and admin
before taking its backup. Stop any external writers yourself first. If restore
fails, inspect the error before restarting those services. Rollback uses that directory:

```bash
ansible-playbook -i inventory.local.yml -K oeds-db-rollback.yml \
  -e oeds_rollback_source_dir=/absolute/path/to/postgres-home-pre-cutover \
  -e oeds_enable_crawlers_after_rollback=true
```

For a major-version rollback, also restore the compatible database image in
Compose. Do not start a newer image against an older major-version data directory.
Migration, cutover and rollback are administrator operations, not first-install steps.

## Stop or remove OEDS

```bash
ansible-playbook -i inventory.local.yml -K oeds-uninstall.yml
```

This stops and removes OEDS containers/networks, preserving database volumes,
source, runtime settings and backups. Docker and host-level settings remain.
Use the explicit reset command in the test guide to destroy data as well.
Optional flags `oeds_uninstall_remove_backups=true` and
`oeds_uninstall_remove_images=true` are deliberately not enabled by default.

## Credentials and permissions

Crawler API keys belong in `runtime/crawler/.env`. Service passwords and port
overrides belong in the installed `repo/deploy/.env`. Ansible protects
these files with `root:docker` and mode `0640`. Both crawler containers run as
UID 1000; the runtime config file and the data/log/admin-state directories are
owned by that UID (group `docker`, not world-writable), and every update
re-applies this ownership recursively. Keep the admin port behind SSH or
authenticated access.

The password rotation feature requires the Bitwarden `bw` CLI on the target
and `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_PASSWORD` in the control environment.
Set `BW_SERVER_URL` for a self-hosted vault. It rotates database, readonly,
Grafana and pgAdmin passwords, verifies services and stores credentials in
Bitwarden. It attempts rollback on failure.

```bash
ansible-playbook -i inventory.local.yml -K oeds-rotate-passwords.yml \
  -e oeds_rotation_deployment_name=intern-test
```

Use `-e oeds_rotation_dry_run=true` for a preview. Direct host invocation is
`python3 oeds_ops/password_rotation.py --dry-run` from `repo/deploy`. Real Bitwarden writes require
separate vault credentials and are not covered by fixture tests.

## Status email

The optional `oeds_mail` Ansible callback uses `OEDS_EMAIL_MAILHOST`,
`OEDS_EMAIL_FROMADDR` and comma-separated `OEDS_EMAIL_TOADDRS`. Dedicated
`OEDS_ANSIBLE_EMAIL_*` settings override crawler mail settings. For authenticated
SMTP, set `OEDS_ANSIBLE_EMAIL_USERNAME`, `OEDS_ANSIBLE_EMAIL_PASSWORD` and
`OEDS_ANSIBLE_EMAIL_STARTTLS=true`. Identical messages are limited to one per
hour by default; `OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS` changes this interval.

Test without sending mail using `OEDS_ANSIBLE_EMAIL_DRY_RUN=true` and
`OEDS_ANSIBLE_EMAIL_DRY_RUN_FILE=/tmp/oeds-status.eml`. Live delivery depends on
your SMTP service. Syntax errors before callback initialization cannot send mail.

## Playbooks

| File | Purpose |
| --- | --- |
| `oeds-install-host-prep.yml` | OS repositories, SELinux policy, Docker packages |
| `oeds-install-core.yml` | Database, Grafana, pgAdmin and PostgREST |
| `oeds-install-post.yml` | Post-processing SQL functions, safe to rerun |
| `oeds-install-crawlers.yml` | Complete stack including scheduler/admin; also the update |
| `oeds-deploy.yml` | Stage, build, optional backup, switch; imported by both install playbooks |
| `oeds-smoke-test.yml` | Service/database health checks, `oeds-crawl --list` and an offline crawler run in the built image |
| `oeds-db-backup.yml`, `oeds-db-migrate.yml`, `oeds-db-rollback.yml` | Database recovery lifecycle |
| `oeds-rotate-passwords.yml` | Bitwarden-backed credential rotation |
| `oeds-uninstall.yml` | Conservative removal or explicitly confirmed reset |
