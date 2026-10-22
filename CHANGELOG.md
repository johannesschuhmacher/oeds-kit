# Changelog

The former module repositories keep their own history in
`packages/*/CHANGELOG.md` and `deploy/CHANGELOG.md`.

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
