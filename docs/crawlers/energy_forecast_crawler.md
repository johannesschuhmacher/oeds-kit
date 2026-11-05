# Energy Forecast

Price forecasts for the next 48 hours for the market zone DE-LU from
[energyforecast.de](https://www.energyforecast.de)
(`/api/v1/predictions/next_48_hours`).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/energy_forecast_crawler.py` |
| Schema | `energy_forecast` |
| Access | API token (`ENERGY_FORECAST_TOKEN`) |
| Licence | Proprietary |
| Resolution | 15 minutes |
| Dashboard | `Crawlers/energy_forecast_crawler.json` |

## Data

The crawler requests quarter-hourly prices with `fixed_cost_cent=0` and
`vat=0`, keeps the slots that start now or later and writes the first 192
(48 hours) as one row.

| Table | Content | Key |
| --- | --- | --- |
| `predictions_48h` | Price `p_h_HH_m_MM` and price origin `o_h_HH_m_MM` (the API's `price_origin`) for each quarter hour, `HH:MM` after `prediction_start` | `prediction_start` |

`prediction_start` is the start of the first future slot in UTC (`timestamp
with time zone`). The price unit is not stated in the crawler; the dashboard
multiplies `p_h_*` by 1000 and labels the result EUR/MWh. Missing slots at the
end are left empty. Each run updates the row of `energy_forecast` in
`public.metadata`.

## Configuration

```yaml
energy_forecast_crawler:
  enable: false
  schema_name: energy_forecast
  description: Crawls Energy Price Forecasts (Next 48h)
  schedule: 0 4,16 * * *
```

The crawler reads no other config keys. The token comes from the environment
or from the `.env` file in the module's folder
(`packages/crawler-pack/src/crawler/.env`).

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl energy_forecast_crawler
```

## Notes

- A run with the same `prediction_start` overwrites the stored row.
- Each run also appends its row to `energy_forecast_history.csv` in
  `OEDS_CRAWLER_DATA_DIR` (default `crawler/data`).
- A missing token, an HTTP error or an answer without future slots fails the
  run.
