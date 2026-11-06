# ENTSO-E Web API

Day-ahead prices, the load forecast and the wind and solar forecast for one
bidding zone from the
[ENTSO-E Transparency Platform Web API](https://web-api.tp.entsoe.eu/api),
read with the `entsoe-py` client. The crawler refreshes a short window around
today for the day-ahead price forecast; `entsoe_fms` loads the long history
from the File Library.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/entsoe_api.py` |
| Schema | `entsoe_api` |
| Access | Web API security token `ENTSOE_API_KEY` (or `ENTSOE_SECURITY_TOKEN`, `ENTSOE_API`) |
| Licence | not stated; `public.metadata` records "ENTSO-E Transparency Platform terms and conditions" |
| Resolution | as published by the API |
| Dashboard | `Crawlers/entsoe_api.json` |

## Data

The crawler loads four datasets for `country_code` (default `DE_LU`): SDAC
day-ahead prices, EXAA day-ahead prices (ENTSO-E price sequence 2), the load
forecast and the wind and solar forecast.

| Table | Content | Key |
| --- | --- | --- |
| `day_ahead_prices` | `price_eur_mwh` in EUR/MWh, `currency` `EUR`; SDAC rows have `sequence` 1 and `source_market` `SDAC`, EXAA rows `sequence` 2 and `source_market` `EXAA` | `market_area`, `sequence`, `delivery_start_utc` |
| `load_forecasts` | `load_mw` in MW for each `metric` (column label of the `entsoe-py` result) | `market_area`, `process_type`, `metric`, `delivery_start_utc` |
| `wind_solar_forecasts` | `forecast_mw` in MW for each `psr_type` (column label of the `entsoe-py` result) | `market_area`, `process_type`, `psr_type`, `delivery_start_utc` |

The keys are unique constraints; rows are upserted. `delivery_start_utc`,
`delivery_end_utc` and `download_time_utc` are stored with time zone, in UTC.
The API gives only the start of each interval: `delivery_end_utc` is the start
of the next row, and the last row gets the median spacing of the series. Each
run also updates the row of `entsoe_api` in `public.metadata` (source, covered
window).

## Configuration

```yaml
entsoe_api:
  enable: false
  schema_name: entsoe_api
  description: Crawls selected ENTSO-E Transparency Platform Web API time series
  schedule: 35 12 * * *
  post_run_scripts:
  - oeds-post forecast day-ahead-price
  country_code: DE_LU
  lookback_days: 14
  lookahead_days: 2
  request_pause_seconds: 0.5
  include_day_ahead_prices: true
  include_exaa_prices: true
  include_load_forecast: true
  include_wind_solar_forecast: true
  jobs:
    forecast_daily:
      enable: false
      schedule: 35 12 * * *
      lookback_days: 14
      lookahead_days: 2
      run_post_scripts: true
    training_bootstrap:
      enable: false
      schedule: 10 3 * * 0
      lookback_days: 120
      lookahead_days: 2
      run_post_scripts: false
    energy_arena:
      enable: false
      schedule: 40 9,10 * * *
      lookback_days: 14
      lookahead_days: 2
      run_post_scripts: true
      post_run_scripts:
      - oeds-post forecast day-ahead-price --backtest-days 0
      - oeds-post submit energy-arena
```

The window runs from midnight (Europe/Berlin) `lookback_days` before today to
midnight `lookahead_days` after today. `start_date` replaces the lookback with
a fixed start (a value without time zone is read as Europe/Berlin).
`target_datasets` (a list of `day_ahead_prices`, `exaa_day_ahead_prices`,
`load_forecast`, `wind_solar_forecast`) replaces the `include_*` switches.
`process_type` (default `A01`) is used for both forecasts. `api_key` is read
only when none of the environment variables is set.

After a scheduled run of a job with `run_post_scripts: true`, the scheduler
runs `oeds-post forecast day-ahead-price` (`packages/post`), which writes the
schema `price_forecast`.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl entsoe_api
docker exec oeds-scheduler oeds-crawl entsoe_api --job training_bootstrap
```

## Notes

- `forecast_daily` refreshes the last 14 and the next 2 days and then runs
  the price forecast; `training_bootstrap` (Sundays) reloads 120 days without
  running it.
- `energy_arena` runs the forecast before the Energy Arena deadline and
  submits it; see [Energy Arena submission](../energy_arena.md).
- If the API has no data for a dataset, the crawler logs a warning and keeps
  the stored rows.
- Requests are paused by `request_pause_seconds` (0.5 s).
- Without a token the crawler fails at start-up.
