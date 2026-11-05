# Eurostat

Annual values of one [Eurostat](https://www.eurostat.europa.eu/) dataset,
by default `nrg_inf_epcrw`, loaded with the Python package `eurostat`.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/eurostat_crawler.py` |
| Schema | `eurostat` |
| Access | none |
| Licence | not stated |
| Resolution | 1 year |
| Dashboard | `Crawlers/eurostat_crawler.json` |

## Data

The crawler downloads the dataset for `start_year` to `end_year` and turns the
year columns into rows.

| Table | Content | Key |
| --- | --- | --- |
| `eurostat` | `capacity` per `year`, country (`geo\TIME_PERIOD`), `siec` and `plant_tec`, with `freq` and `unit` | `year`, `geo\TIME_PERIOD`, `siec`, `plant_tec` |

The key is the unique constraint `uq_eurostat_year_geo_siec_plant_tec`. The
table is a TimescaleDB hypertable on `year` (integer). `unit` is copied from
the dataset; values are not converted. Each run also updates the row of
`eurostat` in `public.metadata`; its data date (2024-06-12) and covered period
(1990 to 2023) are fixed in the code and do not follow the configured years.

## Configuration

```yaml
eurostat_crawler:
  enable: false
  schema_name: eurostat
  description: Crawls Eurostat data
  dataset_id: nrg_inf_epcrw
  start_year: 2019
  end_year: 2025
  post_run_scripts: null
  schedule: 0 4 * * *
```

`dataset_id`, `start_year` and `end_year` are required. For a dataset other
than `nrg_inf_epcrw` the table is `eurostat_<dataset_id>` (lower case, other
characters replaced by `_`); `table_name` sets the table name explicitly.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl eurostat_crawler
```

## Notes

- Each run loads the whole year range again and upserts on the key, so
  revised values replace old ones.
- Years in the range that the dataset does not contain are skipped. Rows
  without a value are dropped.
- The table has fixed columns, so another dataset must have the dimensions
  `freq`, `siec`, `plant_tec`, `unit` and `geo\TIME_PERIOD`.
