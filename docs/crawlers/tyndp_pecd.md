# TYNDP PECD

Hourly capacity factors of the Pan-European Climate Database (PECD) as
published by ENTSO-E and ENTSOG with the TYNDP scenarios
([TYNDP 2024](https://2024.entsos-tyndp-scenarios.eu/download/),
[TYNDP 2026](https://2026.entsos-tyndp-scenarios.eu/download/)).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/tyndp_pecd.py` |
| Schema | `tyndp_pecd` |
| Access | none |
| Licence | CC BY 4.0, attribution "TYNDP 2024 Scenarios" or "TYNDP 2026 Scenarios" |
| Resolution | 1 hour, 8760 hours per series |
| Dashboard | `Crawlers/tyndp_pecd.json` |

## Data

Each edition is one ZIP archive with one CSV file per target year, PECD zone
and technology; each file has one column per climate year. The archives hold
about 23,500 (2024) and 22,400 (2026) series, 1.3 GB in the database.

| Edition | Archive | Climate years | Target years |
| --- | --- | --- | --- |
| `tyndp2024` | `PECD.zip` of the scenario inputs, PECD 3.1 (files "edition 2023.2") | `1982` to `2019` (38 years; rooftop and utility PV to `2020`) | 2030, 2040, 2050 |
| `tyndp2026` | `PECD.zip` of the National Trends model input | 30 weather scenarios per target year: `WS001` to `WS030` (2030), `WS031` to `WS060` (2035), `WS061` to `WS090` (2040), `WS091` to `WS120` (2050) | 2030, 2035, 2040, 2050 |

| Table | Content | Key |
| --- | --- | --- |
| `capacity_factors` | `capacity_factor` as `real[]` with 8760 values (hour 1 = first hour of 1 January), `source_technology` and `source_file` | `edition`, `target_year`, `zone`, `technology`, `climate_year` |
| `editions` | `Last-Modified` and size of the loaded archive, number of files and series, load time | `edition` |
| `access_status` | One row on the access model of the source (public download) | `source_name` |

`zone` is the PECD zone of the file name (bidding zones such as `DE00`,
`DKW1`, offshore nodes such as `DKN6_OFF` or `NL033`). `technology` is one of
`wind_onshore`, `wind_offshore`, `solar_pv` (TYNDP 2024 "LFSolarPV"),
`solar_pv_rooftop`, `solar_pv_utility`, `csp_no_storage`,
`csp_storage_7h_predispatch` and `csp_storage_7h_dispatched`; the name in the
file is kept in `source_technology`.

Views: `capacity_factors_hourly` unnests the arrays into one row per hour
(`hour_of_year` 1 to 8760); filter it on `edition`, `zone` and `technology`.
`series_summary` counts zones, climate years and series per edition, target
year and technology. Each run updates the row of `tyndp_pecd` in
`public.metadata`.

```sql
SELECT climate_year, avg(capacity_factor) AS mean_cf
FROM tyndp_pecd.capacity_factors_hourly
WHERE edition = 'tyndp2026' AND target_year = 2030
  AND zone = 'DE00' AND technology = 'wind_onshore'
GROUP BY climate_year
ORDER BY climate_year;
```

## Configuration

```yaml
tyndp_pecd:
  enable: false
  schema_name: tyndp_pecd
  description: Loads the TYNDP 2024 and 2026 PECD hourly capacity factors
  schedule: 15 2 * * 6
```

`editions` (default both) limits the editions loaded. `request_timeout_seconds`
(default 120) and `user_agent` set the HTTP requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl tyndp_pecd
```

## Notes

- The archives are 1.4 GB (2024) and 0.8 GB (2026). A run compares
  `Last-Modified` and size of each archive with `editions` and downloads only
  a changed or new archive to `crawler/data/tyndp_pecd/`; the file is deleted
  after loading.
- An edition is replaced in one transaction; a failed load keeps the previous
  data.
- The TYNDP 2024 archive also holds an `.xlsx` copy of one CSV file (zone
  `ITCS`, `solar_pv_utility`, 2040); it is not read.
- A file without exactly 8760 hourly rows stops the run with the file name.
