# DWD CDC

Monthly regional climate averages for Germany and its federal states from the
[DWD Climate Data Center](https://www.dwd.de/EN/ourservices/cdc/cdc_ueberblick-klimadaten_en.html)
(`https://opendata.dwd.de/climate_environment/CDC/regional_averages_DE/monthly`).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/dwd_cdc.py` |
| Schema | `dwd_cdc` |
| Access | none |
| Licence | DWD open data terms, attribution required |
| Resolution | 1 month |
| Dashboard | `Crawlers/dwd_cdc.json` |

## Data

The crawler loads three variables: mean air temperature (`degC`),
precipitation (`mm`) and sunshine duration (`h`). DWD publishes one file per
variable and calendar month with all years
(`<variable>/regional_averages_<tm|rr|sd>_<MM>.txt`), so a run reads 36 files.

| Table | Content | Key |
| --- | --- | --- |
| `regional_monthly` | `value` and `unit` per `variable`, `year`, `month` and `region` (a federal state or `Deutschland`), with `source_url` and the file's creation date `source_created_at` | `variable`, `year`, `month`, `region` |
| `access_status` | One row on the access model of the source (public download) | `source_name` |

`period_start` is the first day of the month at 00:00 UTC (`timestamp with
time zone`); `fetched_at` is the run time in UTC. The region names are the
column headers of the DWD files.

Views: `germany_monthly` (rows with `region = 'Deutschland'`) and
`regional_summary` (observations, first and last month and last fetch per
variable and region). Each run updates the row of `dwd_cdc` in
`public.metadata`.

## Configuration

```yaml
dwd_cdc:
  enable: false
  schema_name: dwd_cdc
  description: Crawls DWD Climate Data Center monthly regional German climate averages
  schedule: 25 3 * * 0
```

`variables` replaces the three default variables; each entry needs `id`,
`path`, `prefix` and `unit`. `months` (default 1 to 12) limits the calendar
months loaded. `request_timeout_seconds` (default 90) and `user_agent` set the
HTTP requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl dwd_cdc
```

## Notes

- Each run downloads all files first and then replaces the whole content of
  `regional_monthly`; a failed download stops the run before anything is
  deleted.
- Failed requests are retried up to four times.
