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

The automated host preparation targets CentOS Stream and currently sets SELinux
to permissive mode. Review this host-wide security change with your administrator.
Ubuntu host setup has not been verified. Docker access grants host-level control;
only trusted operators should join the `docker` group.

## Update without losing settings

Assemble the new source outside the installed `repo/` directory first. For
private repositories, use your Git credential helper or the installer's
temporary `GIT_ASKPASS` token mechanism. Never embed credentials in clone URLs.

```bash
ansible-playbook -i inventory.local.yml -K oeds-update.yml \
  -e oeds_repo_source_mode=local_worktree \
  -e oeds_repo_local_src="$HOME/oeds-assembled" \
  -e oeds_enable_crawlers=true
ansible-playbook -i inventory.local.yml -K oeds-install-post.yml
ansible-playbook -i inventory.local.yml -K oeds-smoke-test.yml \
  -e oeds_expect_crawler_admin=true
```

An update backs up the database, replaces source code, preserves crawler
settings and Compose passwords/ports, and restarts services. It does not
replace existing Docker volumes. `oeds_update_docker_packages=true` also
updates Docker packages; normal updates leave them alone. PostgreSQL major
version changes require a separate migration, not an ordinary update.

Advanced source modes: `git` clones deployment and assembles its pinned
dependencies on the target (requires Git access there); `local_worktree`
transfers a prepared workspace, including intended uncommitted changes;
`local_archive` transfers a committed Git archive. The last mode only works
with a repository that actually contains the complete assembled workspace.
Use `local_worktree` for the modular layout.

## Backup and restore

```bash
ansible-playbook -i inventory.local.yml -K oeds-db-backup.yml
ansible-playbook -i inventory.local.yml -K oeds-db-migrate.yml \
  -e oeds_apply_cutover=false
```

The first command stores a private logical backup and runtime settings under
`/open_energy_data_server/backups`. The second restores into a separate staging
database on port 6543. Compare row counts and query results before continuing.
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
overrides belong in the installed deployment module's `.env`. Ansible protects
these files with `root:docker` and mode `0640`. Runtime data/log directories are
writable by the container's UID 1000 and trusted Docker operators; they are not
world-writable. The admin container currently uses root to edit the bound
configuration file. Keep the admin port behind SSH or authenticated access.

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
`python3 oeds_ops/password_rotation.py --dry-run` from the deployment module,
not the old monorepository `scripts/` path. Real Bitwarden writes require
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
| `oeds-install-crawlers.yml` | Complete stack including scheduler/admin |
| `oeds-update.yml`, `oeds-update-crawlers.yml` | Source update and database backup |
| `oeds-smoke-test.yml` | Service/database health checks |
| `oeds-db-backup.yml`, `oeds-db-migrate.yml`, `oeds-db-rollback.yml` | Database recovery lifecycle |
| `oeds-rotate-passwords.yml` | Bitwarden-backed credential rotation |
| `oeds-uninstall.yml` | Conservative removal or explicitly confirmed reset |
