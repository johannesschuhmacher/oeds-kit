# Open-Meteo

Hourly DWD ICON weather forecasts from the
[Open-Meteo DWD API](https://open-meteo.com/en/docs/dwd-api)
(`https://api.open-meteo.com/v1/dwd-icon`) on a 1-degree grid over the
ENTSO-E countries, with country averages and simple derived indices for energy
analyses.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/open_meteo.py` |
| Schema | `open_meteo` |
| Access | none for non-commercial use; optional API key `OPEN_METEO_API_KEY` for commercial plans |
| Licence | CC BY 4.0 (Open-Meteo); the free API is for non-commercial use only |
| Resolution | 1 hour, 1 degree |
| Dashboard | `Crawlers/open_meteo.json` (also used by `Analyses/energy_weather.json`) |

## Data

The grid has 667 points: every full degree from 35° N to 71° N and 10° W to
31° E that lies on land of one of 34 ENTSO-E countries
(`crawler/data/open_meteo_grid.json`). Offshore points are not included.
`deploy/tools/make_open_meteo_grid.py` builds the file from the Natural Earth
1:110m countries (public domain).

Each run requests 15 hourly variables for every point, from `past_hours`
before now to `forecast_hours` ahead, in requests of 50 points.

| Table | Content | Key |
| --- | --- | --- |
| `locations` | Name (e.g. `52°N 13°E`), country, coordinates, `elevation_m` (from the API), `aggregation_weight` = cos(latitude), `enabled` | `location_id` (e.g. `de_52_13`) |
| `entsoe_country_aliases` | Maps ENTSO-E area names (e.g. `DE(Amprion)`, `DK1`) to `country_code` | `entsoe_area_name` |
| `runs` | Kept runs: `retrieved_at`, number of locations and rows | `retrieved_at` |
| `hourly_forecast` | Temperature and apparent temperature (°C), humidity, precipitation probability and cloud cover (%), precipitation (mm), wind speed at 10, 80 and 120 m and gusts (m/s), wind direction (deg), shortwave, direct and diffuse radiation (W/m²), `weather_code` and `weather_label`, derived indices | `location_id`, `weather_model`, `retrieved_at`, `forecast_time` |

`forecast_time` is the API's hourly time stamp in UTC. `retrieved_at` is the run
time in UTC, cut to the minute. After each run only the newest run and the
first run of each UTC day are kept; the forecasts of all other runs are
deleted. The daily runs allow forecasts to be compared with later
observations. `weather_model` is always `dwd_icon`. `hourly_forecast` is made a
TimescaleDB hypertable on `forecast_time` when possible.

The derived columns are `heating_degree_18c` = max(18 − T, 0),
`cooling_degree_22c` = max(T − 22, 0), `solar_generation_index` = shortwave
radiation / 1000 clipped to 0..1, `wind_generation_index` = (wind speed at
80 m / 12)³ capped at 1, `renewables_weather_index` = 0.55 wind + 0.45 solar
index, and `load_weather_index` = heating degree + 0.75 cooling degree.

Views: `latest_hourly_forecast` (the newest run, enabled locations only),
`latest_country_hourly_forecast` (averages per country weighted by
`aggregation_weight`, i.e. by grid-cell area, with the number of points) and
`price_forecast_weather_features` (the country view with `market_area`, `DE`
mapped to `DE_LU`, and `delivery_start_utc`). Each run updates the row of
`open_meteo` in `public.metadata`.

## Configuration

```yaml
open_meteo:
  enable: false
  schema_name: open_meteo
  description: Crawls hourly DWD ICON weather forecasts from Open-Meteo on a 1-degree grid
    over Europe
  schedule: 45 */3 * * *
  forecast_hours: 120
  past_hours: 24
```

`locations` replaces the grid; each entry needs `location_id`, `name`,
`country_code`, `country_name`, `latitude` and `longitude`, and may set
`aggregation_weight` (default 1.0). `batch_size` (default 50) sets the points
per request, `calls_per_minute` (default 500) the pace, `request_timeout_seconds`
(default 90) and `user_agent` the HTTP request. With `api_key` or
`OPEN_METEO_API_KEY` in the crawler `.env`, the crawler uses the customer API.

## API limits

The free API allows 600 calls per minute, 5,000 per hour and 10,000 per day.
A request with more than 10 variables counts as (variables / 10) calls per
location, so one run of the grid counts as about 1,000 calls and takes about
two minutes; eight runs a day (every three hours) stay below the daily limit.
Other Open-Meteo requests from the same address count towards the same limits.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl open_meteo
```

## Notes

- Requests are retried up to five times with growing pauses, because
  Open-Meteo answers 503 when overloaded. A request that still fails is
  logged and its points are skipped; the run fails only when no request
  returns data.
- Until release 1.4.0 there were two Open-Meteo crawlers: `open_meteo` (five
  German locations, one row per variable) and `weather_forecast` (15 cities,
  schema `weather`). The first run of this crawler replaces the tables of the
  former `open_meteo`; the schema `weather` is no longer written and can be
  dropped.
- `price_forecast_weather_features` has the columns of the former `weather`
  view; the country averages now come from the grid instead of a few weighted
  cities. The day-ahead price forecast in `packages/post` does not use the
  view: it reads the kept daily runs from `hourly_forecast`, so that its
  training days see forecasts of the same age as the target day (see
  [Energy Arena](../energy_arena.md)).
