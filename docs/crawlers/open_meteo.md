# Open-Meteo

Hourly DWD ICON weather forecasts for a few German locations from the
[Open-Meteo DWD API](https://open-meteo.com/en/docs/dwd-api).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/open_meteo.py` |
| Schema | `open_meteo` |
| Access | none; optional API key `OPEN_METEO_API_KEY` for commercial plans |
| Licence | not stated (the metadata refers to the Open-Meteo terms, attribution where applicable) |
| Resolution | 1 hour |
| Dashboard | `Crawlers/open_meteo.json` |

## Data

By default the crawler loads `temperature_2m`, `wind_speed_10m`,
`wind_speed_80m`, `shortwave_radiation`, `direct_radiation`, `precipitation`
and `cloud_cover` for Berlin, Hamburg, Munich, Essen and Cuxhaven from
`https://api.open-meteo.com/v1/dwd-icon`.

| Table | Content | Key |
| --- | --- | --- |
| `locations` | `name`, `latitude`, `longitude`, `updated_at` of the configured locations | `location_id` |
| `hourly_forecast` | `value` and `unit` per `variable`, `fetched_at` | `location_id`, `valid_time`, `variable` |
| `latest_hourly_forecast` | View: last `valid_time` per `location_id` and `variable` | |
| `location_summary` | View: forecast hours, first and last `valid_time`, last fetch per location and variable | |
| `access_status` | Whether an API key is configured | `source_name` |

`valid_time` is the hour the value is valid for, requested in UTC and stored
with time zone. `unit` is the unit the API returns for the variable
(`hourly_units`). `fetched_at` is the UTC time of the run. Each run also
updates the row of `open_meteo` in `public.metadata`.

## Configuration

```yaml
open_meteo:
  enable: false
  schema_name: open_meteo
  description: Crawls Open-Meteo DWD ICON weather forecasts for energy-relevant locations
  schedule: 45 */3 * * *
  forecast_days: 5
  past_days: 1
```

`forecast_days` (default 5) and `past_days` (default 1) set the requested
range. `locations` (list of `id`, `name`, `latitude`, `longitude`) and
`hourly_variables` replace the defaults, `api_url` the endpoint. The API key
comes from `api_key` or `OPEN_METEO_API_KEY` in the crawler `.env`.
`user_agent` and `request_timeout_seconds` (default 90) set the HTTP
settings.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl open_meteo
```

## Notes

- Each run replaces `locations` and deletes all `hourly_forecast` rows in the
  returned time range before writing the new forecast. Only the newest
  forecast for each hour is kept; older forecast runs are overwritten.
- If one location fails, the run fails and no forecast is written.
