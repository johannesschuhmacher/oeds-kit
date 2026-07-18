# Intern-Test VM Fresh Checkout Test, 2026-06-11

## Scope

Target host:

```text
iip-vm-oeds-intern-test.iip.kit.edu
```

Source:

```text
C:\Users\js2644\PycharmProjects\oeds
```

The local, unpublished working tree was exported to the VM and installed from:

```text
/home/oeds/oeds-vm-test-export-fresh
```

No GitHub or GitLab remote was used.

## Commands Covered

The test covered the deployment path that is needed before publishing the split:

1. Back up the existing runtime `crawler/.env`.
2. Run destructive Ansible uninstall:
   - remove repo
   - remove runtime
   - destroy Docker data
   - keep backups and images
3. Restore runtime `crawler/.env` before install.
4. Install from the local working tree with:

   ```text
   oeds_repo_source_mode=local_worktree
   oeds_repo_local_src=/home/oeds/oeds-vm-test-export-fresh
   oeds_enable_crawlers=true
   ```

5. Run the install smoke test.
6. Run `oeds-update.yml` from the same local working tree.
7. Run the final smoke test.
8. Run the new bounded `ninja` smoke mode against the fresh database.

## Result

Passed after one deployment fix.

Final running containers:

| Container | Result |
| --- | --- |
| `open-data` | up and healthy |
| `postgrest` | up on `127.0.0.1:3001` |
| `grafana` | up on `127.0.0.1:3006` |
| `pgadmin` | up on `127.0.0.1:8080` and `127.0.0.1:8443` |
| `oeds-scheduler` | up |
| `oeds-crawler-admin` | up on `127.0.0.1:3010` |

The Ansible smoke summary reported:

```text
PostgreSQL 18.3
non_system_tables=49
postgrest=http://127.0.0.1:3001/
grafana=http://127.0.0.1:3006/api/health
```

The Ninja bounded smoke run wrote:

| Table | Rows |
| --- | ---: |
| `ninja.capacity_wind_on` | 3 |
| `ninja.capacity_wind_off` | 3 |
| `ninja.capacity_solar_merra2` | 3 |

## Issue Found and Fixed

The first fresh install failed at the PostgREST smoke check. PostgreSQL was
healthy, but PostgREST restarted because the `readonly` role was missing.

Root cause:

```text
docker/initdb/09-bootstrap-roles.sh
```

was exported from the Windows working tree with CRLF line endings. The
Timescale/PostgreSQL container sources shell scripts from
`/docker-entrypoint-initdb.d`; with CRLF the script failed with:

```text
/docker-entrypoint-initdb.d/09-bootstrap-roles.sh: line 5: $'\r': command not found
```

Fix:

- added repository `.gitattributes` with `*.sh text eol=lf`
- added deployment-module `.gitattributes` with the same shell rule
- normalized the DB bootstrap shell scripts to LF
- re-exported the working tree
- re-ran destructive uninstall, install, update, smoke test, and Ninja smoke

## Local Follow-Up

The `local_worktree` Ansible source mode is now required for unpublished local
testing because `local_archive` uses `git archive` and therefore excludes
uncommitted and untracked files.

Before public release, use `git` or `local_archive` from a committed ref. Use
`local_worktree` only for internal validation of an uncommitted workspace.
