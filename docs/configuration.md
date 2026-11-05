# Crawler configuration

All crawlers and their schedules are set in one file,
`/open_energy_data_server/runtime/CRAWLER_CONFIG.yml` on an installed server.
The first installation copies it from `deploy/CRAWLER_CONFIG.yml`; updates keep
your copy. Edit it directly or on the configuration tab of a crawler in the
admin UI (`http://127.0.0.1:3010/admin`). The scheduler rereads the file when it
changes.

API keys and passwords do not belong in this file. They go into
`/open_energy_data_server/runtime/crawler/.env`; the variable names are listed
in `packages/crawler-pack/src/crawler/.env.example` and on the crawler pages.

## Structure

```yaml
default:            # applies to every crawler
  enable: false
  schedule: 0 4 * * *
  database_uri: postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=
  max_parallel_runs: 3
  email: {...}
smard:              # one section per crawler, named as in `oeds-crawl --list`
  enable: true
  schema_name: smard
  schedule: 0 4 * * *
entsoe_fms:
  schema_name: entsoe_fms
  jobs:             # optional named jobs, each scheduled on its own
    latest_hourly:
      enable: true
      schedule: 0 * * * *
      mode: fms_package_refresh
```

A crawler gets the `default` section, overridden by its own section, overridden
by the job (nested mappings are merged key by key). `oeds-crawl` and the
scheduler build this merged config the same way, so a run by hand behaves like
a scheduled run.

## Scheduler keys

These keys are read by the scheduler and are not passed to the crawler.

| Key | Meaning |
| --- | --- |
| `enable` | `true` schedules the crawler or job; anything else leaves it off. A job inherits the value of its section unless it sets its own. |
| `schedule` | Cron expression with five fields. It is evaluated in the container's local time, which is UTC. |
| `jobs` | Named variants of a crawler, each with its own schedule and settings. Run one by hand with `oeds-crawl <crawler> --job <job>`. |
| `post_run_scripts` | Commands run after a successful run, for example `oeds-post gapfill entsoe-fms`. |
| `run_post_scripts` | `false` skips the `post_run_scripts` for this crawler or job (default `true`). |
| `run_timeout_seconds` | Kill the run after this many seconds and mark it failed (default: no limit). |

## Settings in `default`

| Key | Meaning |
| --- | --- |
| `database_uri` | Database the crawlers write to. The scheduler also uses it for the PostgreSQL advisory lock that keeps a crawler from running twice at once. |
| `max_parallel_runs` | Maximum number of runs at the same time (default 3). Further due runs wait. |
| `email` | `mailhost`, `fromaddr`, `toaddrs`, `subject`, `username`, `password` for the alert mail on a failed run. The `OEDS_EMAIL_*` variables in `crawler/.env` override them, so the password need not be in this file. |

## Crawler keys

| Key | Meaning |
| --- | --- |
| `schema_name` | Database schema the crawler writes to (default: the crawler name). |
| `description` | Text shown in the admin UI. |

All other keys belong to the crawler and are described on its page under
[Crawlers](crawlers/index.md).

## Runs and logs

Each scheduled run is an `oeds-crawl` process with its own log in
`runtime/logs/runs/<crawler>-<job>-<YYYYMMDD-HHMMSS>.log`. The log ends with
`# finished: succeeded`, `failed` or `skipped`; the 200 newest logs are kept.
`oeds-crawl` exits with 0 on success, 1 on failure and 3 when the crawler
skipped the run, for example because a key is missing.
