# World Bank commodity prices

Monthly commodity prices of the World Bank Pink Sheet
([Commodity Markets](https://www.worldbank.org/en/research/commodity-markets)):
coal, crude oil, natural gas and LNG, as well as metals, fertilizers and
agricultural commodities, from 1960, in nominal US dollars.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/worldbank_commodities.py` |
| Schema | `worldbank_commodities` |
| Access | none |
| Licence | CC BY 4.0, "World Bank Commodity Price Data (The Pink Sheet)" |
| Resolution | 1 month |
| Dashboard | `Crawlers/worldbank_commodities.json` |

## Data

The crawler reads the link to the current `CMO-Historical-Data-Monthly.xlsx`
from the Commodity Markets page (the address changes with every monthly
release) and loads the sheet `Monthly Prices`.

| Table | Content | Key |
| --- | --- | --- |
| `monthly_prices` | `price` and `unit` (for example `$/bbl`, `$/mt`, `$/mmbtu`) per `commodity` and month, with `source_url` | `commodity`, `year`, `month` |
| `access_status` | One row on the access model of the source (public download) | `source_name` |

`commodity` is the column header of the workbook without footnote marks.
`period_start` is the first day of the month at 00:00 UTC.

The view `energy_prices` holds the energy series: `Crude oil, average`,
`Crude oil, Brent`, `Crude oil, Dubai`, `Crude oil, WTI`, `Coal, Australian`
(Newcastle), `Coal, South African` (Richards Bay), `Natural gas, US` (Henry
Hub), `Natural gas, Europe` (TTF) and `Liquefied natural gas, Japan`. Each run
updates the row of `worldbank_commodities` in `public.metadata`.

## Configuration

```yaml
worldbank_commodities:
  enable: false
  schema_name: worldbank_commodities
  description: Loads the World Bank Pink Sheet monthly commodity prices (coal, oil, gas)
  schedule: 45 6 * * *
```

`request_timeout_seconds` (default 90) and `user_agent` set the HTTP requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl worldbank_commodities
```

## Notes

- The World Bank publishes the workbook in the first days of each month and
  revises recent months, so each run replaces the whole table.
- Monthly prices exist only in nominal US dollars; daily oil and Henry Hub
  prices come from the [EIA](eia.md) job `fuel_prices_daily`.
