# oeds-kit

KIT additions to the [Open Energy Data Server](https://github.com/open-energy-data-server/open-energy-data-server)
(OEDS): the crawler pack, the scheduler with its admin UI, the post-processing
commands and the deployment, in one repository and one `uv` workspace.

| Path | Package / content | Layer |
| --- | --- | --- |
| `packages/crawler-pack` | `oeds-crawler-pack`: KIT crawlers (`crawler.*`), `oeds-crawl` command, `oeds.crawlers` entry points | depends on `oeds` |
| `packages/scheduler` | `oeds-scheduler-ui`: `oeds-scheduler` daemon and `oeds-crawler-admin` web UI | depends on the crawler pack |
| `packages/post` | `oeds-post-scripts`: `oeds-post` gapfill, backfill, forecast and SQL refresh commands | optional on top |
| `deploy/` | Docker Compose, the runtime image, Ansible playbooks, Grafana provisioning, integration tests | installs all of the above |

The layering is `oeds < crawler-pack < scheduler < post`: the upstream `oeds`
package (pinned to a Git revision of the
[core test branch](https://github.com/johannesschuhmacher/oeds-core) in
`pyproject.toml`, with its crawler dependencies `oeds[crawlers]`) provides
`BaseCrawler` and the upstream crawlers; the crawler pack subclasses it, and
`oeds-crawl` runs both pack and core crawlers (`oeds-crawl --list`; a pack crawler
replaces a core crawler of the same name); the scheduler starts `oeds-crawl` subprocesses and imports
only `crawler.common.*`; the post-scripts are optional for the scheduler and
need the pack only for `oeds-post backfill entsoe-unavailability` (extra
`backfill`).

## Install on a Linux VM

Run inside the VM (CentOS Stream; Git, Python 3.12+ and sudo required). The
installer clones this repository, runs the Ansible playbooks from
`deploy/playbooks` and builds the runtime image from `uv.lock`.

```bash
git clone https://github.com/johannesschuhmacher/oeds-kit.git
cd oeds-kit
bash deploy/tools/oeds_clean_install_from_git.sh --crawler-env-file "$HOME/crawler.env"
```

The environment file with the source API keys is optional. Re-running the
command updates an installed host (`--backup` dumps the database first);
`--ref` installs a branch, tag or commit. The managed installation lives in
`/open_energy_data_server` (`repo/` is this repository, `runtime/` holds
`CRAWLER_CONFIG.yml`, `crawler/.env`, `crawler/data`, logs and admin state);
see [deploy/README.md](deploy/README.md) for the services, ports and files, and
[deploy/playbooks/README.md](deploy/playbooks/README.md) for update, backup,
password rotation and removal.

## Develop locally

One lock file for the whole workspace:

```bash
uv sync --all-packages --all-extras
uv run --package oeds-crawler-pack pytest packages/crawler-pack/tests
uv run --package oeds-scheduler-ui pytest packages/scheduler/tests
uv run --package oeds-post-scripts pytest packages/post/tests
uv run pytest deploy/tests
```

Run a crawler by hand against a database (the same command every scheduled
job runs):

```bash
uv run oeds-crawl --list --config deploy/CRAWLER_CONFIG.yml
OEDS_DB_HOST=localhost OEDS_DB_PORT=6432 OEDS_DB_PASSWORD=opendata \
  uv run oeds-crawl smard --config deploy/CRAWLER_CONFIG.yml
```

`deploy/CRAWLER_CONFIG.yml` is the seed copied to `runtime/CRAWLER_CONFIG.yml`
on the first install; all crawlers start disabled. Change a dependency in a
package's `pyproject.toml`, then `uv lock` and commit `uv.lock`; the Docker
image installs exactly that lock (`uv sync --frozen`). The `oeds` revision is
pinned in the root `[tool.uv.sources]`.

## Update an installation

```bash
cd oeds-kit && git pull
bash deploy/tools/oeds_clean_install_from_git.sh --crawler-env-file "$HOME/crawler.env"
```

or, from `deploy/playbooks` on the VM, `ansible-playbook -i inventory.local.yml -K
oeds-install-crawlers.yml -e oeds_repo_local_src=/path/to/oeds-kit`. The
running services keep going while the new images build; add `--backup` for a
database dump first.

## Licence

AGPL-3.0-or-later, see the `LICENSES/` directory in each part.
