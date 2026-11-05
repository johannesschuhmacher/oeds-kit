# Renewables.ninja

Country-level wind and solar capacity factors for Europe from the
[Renewables.ninja downloads](https://www.renewables.ninja/downloads)
(European datasets, version 1.1).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/ninja.py` |
| Schema | `ninja` |
| Access | none |
| Licence | CC BY 4.0 |
| Resolution | not stated |
| Dashboard | `Crawlers/ninja.json` |

## Data

The crawler downloads one ZIP archive per entry of `datafiles`, reads the
configured CSV file from it and writes one column per country. Country columns
are the lower-case country codes from the CSV header (`DE_ON` becomes `de`).

| Table | Content | Key |
| --- | --- | --- |
| `capacity_wind_on` | Onshore wind capacity factor per country (CSV columns containing `ON`) | none |
| `capacity_wind_off` | Offshore wind capacity factor per country (CSV columns containing `OFF`) | none |
| `capacity_solar_merra2` | Solar PV capacity factor per country (MERRA-2 file) | none |

The time column is the first column of the CSV file, parsed as a timestamp and
written under its name in the file (`time` in the smoke data and in the
dashboard queries). The code does not state its time zone. Each run also
updates the row of `ninja` in `public.metadata` (source, licence, covered
period 1980-01-01 00:00 to 2016-12-31 23:00).

## Configuration

```yaml
ninja:
  schema_name: ninja
  enable: false
  datafiles:
    wind:
      download_url: https://www.renewables.ninja/downloads/ninja_europe_wind_v1.1.zip
      extract_filename: ninja_wind_europe_v1.1_current_on-offshore.csv
    solar:
      download_url: https://www.renewables.ninja/downloads/ninja_europe_pv_v1.1.zip
      extract_filename: ninja_pv_europe_v1.1_merra2.csv
  smoke_mode: false
  smoke_rows: 4
```

Only the keys `wind` and `solar` under `datafiles` are written; other keys are
downloaded and skipped with a warning. `smoke_mode: true` writes a small
synthetic dataset for `DE` instead of downloading (`smoke_rows` hourly rows,
starting at `smoke_start`, default `2016-01-01 00:00:00`). The section sets no
`schedule`, so the default `0 4 * * *` applies.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl ninja
```

## Notes

- Every run replaces the three tables completely (`if_exists="replace"`).
  The tables are plain tables without primary key or hypertable.
- A failed download or a missing CSV file in the archive is logged as an
  error and that file is skipped; the run itself does not fail.
