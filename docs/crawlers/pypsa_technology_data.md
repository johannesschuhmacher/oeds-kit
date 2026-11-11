# PyPSA technology-data

Cost and technology assumptions of
[PyPSA technology-data](https://github.com/PyPSA/technology-data)
([documentation](https://technology-data.readthedocs.io)): investment, fixed
and variable costs, efficiencies, lifetimes and fuel costs per technology, as
PyPSA-Eur uses them.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/pypsa_technology_data.py` |
| Schema | `pypsa_technology_data` |
| Access | none |
| Licence | code GPL-3.0; the data follow the terms of the sources named in `source` |
| Resolution | one value per release, assumption year, technology and parameter |
| Dashboard | `Crawlers/pypsa_technology_data.json` |

## Data

Every release has one file `outputs/costs_<year>.csv` per assumption year
2020, 2025, ..., 2050. The crawler reads the list of releases from the GitHub
API (pre-releases excluded) and the files from `raw.githubusercontent.com`.

| Table | Content | Key |
| --- | --- | --- |
| `costs` | `value`, `unit`, `source`, `further_description` and `currency_year` (empty before v0.7) | `version`, `year`, `technology`, `parameter` |
| `releases` | Release date and the years loaded per release | `version` |
| `access_status` | One row on the access model of the source (public download) | `source_name` |

The view `latest_costs` holds the rows of the newest release. Each run updates
the row of `pypsa_technology_data` in `public.metadata`.

```sql
SELECT year, value, unit, currency_year
FROM pypsa_technology_data.latest_costs
WHERE technology = 'onwind' AND parameter = 'investment'
ORDER BY year;
```

## Configuration

```yaml
pypsa_technology_data:
  enable: false
  schema_name: pypsa_technology_data
  description: Loads the cost assumptions of every PyPSA technology-data release
  schedule: 30 6 * * *
```

`versions` limits the releases loaded (for example `[v0.15.0]`); `years`
replaces the default years. `request_timeout_seconds` (default 60) and
`user_agent` set the HTTP requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl pypsa_technology_data
```

## Notes

- Release files do not change, so a run loads only releases that are not yet
  in `releases`; the first run loads all releases (about 165,000 rows).
- The US cost files (`outputs/US/`) are not loaded.
- Monetary values are in EUR of the row's `currency_year`.
