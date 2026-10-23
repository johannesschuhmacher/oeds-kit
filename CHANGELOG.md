# Changelog

The former module repositories keep their own history in
`packages/*/CHANGELOG.md` and `deploy/CHANGELOG.md`.

## Unreleased

Streamlining without removing features in use; about 7,300 lines less.

- Crawler pack: dead ENTSO-E FMS code and never-created table definitions
  removed; FMS unique constraints built from one key table (identical DDL);
  the localhost `main()` scripts removed; more crawlers write with COPY;
  `copy_insert` keeps empty strings (only `None` becomes NULL); ENTSOG, SMARD
  and FMS use `build_session`.
- Scheduler and admin: "Run once" uses the scheduler's runner (honours
  `run_post_scripts` and timeouts); the config is parsed once per page;
  the gapfill and price-forecast panels recognise the `oeds-post` commands;
  run logs are tailed from the end; per-data-item `lock_keys`, scheduling
  indirection, dead code and unused CSS removed.
- Post-processing: the four dashboard generator scripts removed (the JSON
  files are the source); unused gapfill extensions removed; the gapfiller
  lives in `oeds_gapfill`; price-forecast backends share their code and
  load inputs on one connection. Outputs are unchanged.
- Deployment: one `group_vars/all.yml` instead of `*_effective` variables
  (an `oeds_data_root` override now reaches the backup playbooks); one
  crawler image `oeds-crawler:local` for scheduler and admin; only missing
  images are pulled; no second package run; facts gathered only where needed;
  ownership repaired only under `logs/`; uninstall removes the real backup
  directory; `compose.test.yml` and `smoke_lib.sh` removed.

Decided removals and changes, about 3,200 lines less:

- Admin: the Gapfill Tests page and the in-process special actions
  (weather window, Eurostat range, ENTSO-E targeted run and backfill) are
  removed; the gapfill panel keeps exactly one post-run step, validates its
  fields and shows the last gapfill run; the dashboard and crawler pages
  show scheduler runs and whether a crawler is running (PostgreSQL lock).
- `oeds-post` is a plain dispatcher for its four commands; `--list`,
  `--print-command`, `--json`, `--from-script` and `--migrate-config` are gone.
- The price forecast uses only the upstream LEAR model; the ridge fallback,
  `--model-backend`, `--upstream-repo-path` and `OEDS_PRICE_FORECAST_BACKEND`
  are removed. The GloHydroRes import script is removed.
- Gapfill scores all donor candidates at once: 87 s to 0.4 s on an 8-week
  test series, identical filled values.
- ENTSO-E FMS upserts through COPY and one `INSERT … ON CONFLICT` (shared
  `copy_upsert` with EPEX) and no longer reloads the PyPSA power plant list
  every run; the availability map reads `power_system_data.powersystemdata`.
- Deployment: no core-only install (scheduler and admin always installed);
  Ansible always runs on the VM, with one committed `inventory.yml`; the
  installer's sample-data options are removed; installation is documented
  in `deploy/README.md`, operations in `deploy/playbooks/README.md`. The
  dashboard "ENTSO-E – Power plants and availability" is provisioned.

## 1.1.0 (2026-10-23)

- Installer and updates build the new images in `repo.next/` while the
  running services continue, retry once with an empty build cache, and then
  replace only the changed containers (`up -d`, no `down`). A failed build
  leaves the old services running. The database dump before an update is
  off by default (`--backup` / `oeds_backup_before_update=true`); the update
  waits up to 15 minutes for running crawls (#15).
- One deployment playbook, `oeds-deploy.yml`, replaces `oeds-docker-config.yml`,
  `oeds-update.yml`, `oeds-update-crawlers.yml` and the `tasks/` files; an
  update is a rerun of `oeds-install-crawlers.yml`. The source is always the
  checkout at `oeds_repo_local_src` (the `git` and `local_archive` modes and
  `oeds_update_docker_packages` are removed; use `oeds_package_state=latest`).
  The installer no longer runs the smoke test a second time (#15).
- `copy_insert` writes whole floats as integers, so COPY accepts them in
  bigint columns (#14).

## 1.0.0 (2026-10-22)

First release of the merged repository; the archived module repositories end
here.

- Core crawlers: the pinned `oeds-core` installs `oeds.crawler`, its data
  files and the extra `oeds[crawlers]`; `oeds-crawl` and the scheduler run core
  crawlers when no crawler-pack entry point has the name (#11, #12).
- Crawlers: Trading Hub Europe DataExport API, Copernicus zipped NetCDF (#4);
  EPEX skips unchanged files and upserts through COPY, COPY inserts for MaStR,
  ENTSOG, ninja and DWD, price forecast skips incomplete training days (#5);
  faster MaStR XML parsing and longer download retries (#7); the OSM power
  crawler is removed because Overpass blocks automated clients (#8). Earlier:
  EPEX SFTP reconnects, Netztransparenz Hochrechnung paths (#2), ENTSO-E FMS
  parsing, conditional upserts and UpdateTime indexes (#3).
- Grafana: one dashboard per crawler in `Crawlers/` and cross-source views in
  `Analyses/`; `check_dashboards.py --all` queries every provisioned panel
  (#6, #9).
- Deployment: install and update stop scheduler and admin before the database
  (#10).
- Workspace and image (#1):

- Merge oeds-crawler-pack, oeds-scheduler-ui, oeds-post-scripts and
  oeds-deployment into this repository (`git subtree`, history preserved) as
  one `uv` workspace: `packages/crawler-pack`, `packages/scheduler`,
  `packages/post` and `deploy/`. One root `uv.lock` replaces the three
  per-package lock files, `deploy/docker/requirements.lock` and
  `constraints.txt`; the SQLAlchemy `<2.1`, pandas `<4` and numpy `<3` limits
  are `[tool.uv] constraint-dependencies`. The `oeds` core revision
  (13b508d) is pinned once in the root `[tool.uv.sources]`; the scheduler
  declares its dependency on the crawler pack, the post-scripts declare it as
  the optional extra `backfill`.
- Remove `compatibility.yml`, `tools/assemble_workspace.py`,
  `tools/update_requirements_lock.sh`, `compose.modular.yml` and the
  assembled `modular_repos/` workspace. The deployment installs this
  repository directly: `/open_energy_data_server/repo` is a copy of the clone,
  Compose runs from `repo/deploy`, the runtime config is seeded from
  `deploy/CRAWLER_CONFIG.yml` and the post-processing SQL comes from
  `packages/post/scripts/lib/`. The default repository URL is
  `https://github.com/johannesschuhmacher/oeds-kit.git`; `git` source mode
  clones into `repo/` itself (no `deployment-source/` checkout).
- Rebuild the runtime image in two stages: a builder runs `uv sync --frozen`
  from the lock (third-party dependencies in one layer, the three packages in
  the next) and the `runtime` stage copies only `/app/.venv`, so
  `build-essential` is gone. The former `core`/`crawlers`/`post` targets are
  replaced by the single `runtime` target; `tests/integration.py` keeps its
  layer arguments and runs them all in that image.
- Installer: `bash deploy/tools/oeds_clean_install_from_git.sh` clones
  oeds-kit (`--repo-url`, `--ref`) and runs the playbooks from
  `deploy/playbooks`; no assembly step.
- One GitHub Actions workflow: package and deployment tests, compile and
  syntax checks, a build of the runtime image with the offline crawler test
  against TimescaleDB, and an Ansible syntax check.
