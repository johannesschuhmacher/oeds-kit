# Changelog

## Unreleased

- Pin oeds-core 13b508d (crawlers registered as `oeds.crawlers` entry
  points), the crawler pack 7f4b4d1 (crawlers subclass upstream's
  BaseCrawler through KitCrawler, `oeds-crawl` command, failure alert mail
  sent from the run), the scheduler 19f5d22 (every scheduled job is an
  `oeds-crawl` subprocess with its own log in `runtime/logs/runs/`; at most
  `default.max_parallel_runs` (3) run at once) and post-scripts 14b525b
  (runs without the crawler pack).
- Remove `assembly/crawler-inventory.json` and the scheduler's `--inventory`
  / `--workspace-root` arguments; crawlers are found through the entry
  points. The lock omits `oeds` itself (`--no-emit-package`) because the
  image installs the core editable from the workspace, not from Git.
- Check `oeds-crawl --list` inside the built scheduler image during
  `oeds-smoke-test.yml`.
- Install the crawler image's third-party dependencies from the new
  `docker/requirements.lock` (`uv pip sync`) instead of resolving them
  unpinned at build time; a fresh build had pulled SQLAlchemy 2.1 and broke
  every crawler. Modules are installed with `--no-deps` afterwards and the
  Dockerfile copies sources after the dependency layer. Regenerate the lock
  with `tools/update_requirements_lock.sh` when pins change.
- Run the offline ninja crawler integration test (`tests/integration.py`)
  inside the built scheduler image as part of `oeds-smoke-test.yml`, so an
  image that cannot crawl fails the install instead of the first schedule.
- Dump the database (`pg_dump -Fc` and globals) before every update, also
  when the installer is re-run, into `oeds_backup_dir` (default
  `/home/oeds/backups/<timestamp>`, on the data partition and included in the
  filesystem-size preflight). Only the newest `oeds_backup_keep` (3)
  directories are kept; `oeds_backup_before_update=false` skips the dump.
  `oeds-db-backup.yml` writes to the same directory.
- Run the crawler admin container as the image user (UID 1000) instead of
  root, give the runtime config file and directories to that UID, and repair
  the ownership of existing runtime files on every update. The root admin
  created `logs/<crawler>.log` as root, after which every scheduled crawl in
  the scheduler container failed with `PermissionError` for five days.
- Remove the `oeds-post gapfill smard` post-run script from the default SMARD
  config; it only filled a hard-coded week of June 2024.
- Fix docs: `docker_data/` lives under `oeds_data_root` (`/home/oeds`), not
  under `/open_energy_data_server`; no Git token is needed for the public
  repositories.

- Store Docker persistent volumes and Docker's own data-root (images, build
  cache, logs) on a large, separate data partition instead of the OS root
  filesystem. New `oeds_data_root` variable (default `/home`) drives
  `oeds_data_dir` and the new `oeds_docker_data_root`; `oeds-packages.yml`
  now writes `/etc/docker/daemon.json` with `data-root`, json-file log
  rotation and BuildKit cache GC. Prevents the root partition from filling up
  as the database grows or images are rebuilt.
- Abort the install if the data dir or Docker data-root are on a filesystem
  smaller than `oeds_min_data_filesystem_gb` (default 200 GB), so data cannot
  silently land on a small OS partition again. VMs with a single large
  partition pass the check.

## 0.0.0-local

- Initial local split repository for KIT deployment assets.
- Copied current Compose, Docker, Ansible, provisioning, and ops files.
- Added `compose.modular.yml`, `Dockerfile.crawler-modular`, and a local
  deployment smoke verifier for the repository split.
- Added isolated DB, real SMARD crawler, SMARD post-run, and stack smoke tests.
- Added active configured crawler smoke coverage for ENTSO-E API, ENTSO-E FMS
  EnergyPrices, power-system data, and weather forecast.
- Set modular image `PYTHONPATH=/app` and passed `OEDS_ADMIN_REPO_ROOT=/app`
  for runtime-mounted Admin UI operation.
- Added starter GitHub Actions CI and a `--local-only` deployment repository
  verification mode.
- Install the complete official OEDS crawler requirements on Python 3.13 and
  pass the runtime crawler-config path to post-processing commands.
- Bound ENTSO-E FMS backfills to the requested file period and migrate the
  consumption-unavailability table for current source columns.
- Pin the scheduler constructor audit that rejects unsupported additional
  required parameters in legacy crawler modules.
- Keep the generated Ansible inventory inside a custom `--work-dir` unless an
  explicit `OEDS_ANSIBLE_INVENTORY_FILE` is configured.
- Exclude deployment `.tmp` contents when assembling from a local checkout.
