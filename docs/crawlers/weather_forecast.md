# Weather forecast

Hourly DWD ICON weather forecasts for 15 European cities from the
[Open-Meteo DWD API](https://open-meteo.com/en/docs/dwd-api)
(`https://api.open-meteo.com/v1/dwd-icon`), with simple derived indices for
energy dashboards.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/weather_forecast.py` |
| Schema | `weather` |
| Access | none |
| Licence | not stated (metadata points to the Open-Meteo DWD API docs) |
| Resolution | 1 hour |
| Dashboard | `Crawlers/weather_forecast.json` (also used by `Analyses/energy_weather.json`) |

## Data

Each run requests 14 hourly variables per enabled location, from `past_hours`
before now to `forecast_hours` ahead. The default locations are seven German
cities (Berlin, Hamburg, Frankfurt am Main, Munich, Freiburg, Cuxhaven,
Leipzig) and Vienna, Zurich, Amsterdam, Brussels, Copenhagen, Paris, Warsaw
and Prague.

| Table | Content | Key |
| --- | --- | --- |
| `locations` | Name, country, region, `location_type`, coordinates, `elevation_m` (from the API), `aggregation_weight`, `enabled` | `location_id` |
| `entsoe_country_aliases` | Maps ENTSO-E area names (e.g. `DE(Amprion)`, `DK1`) to `country_code` | `entsoe_area_name` |
| `hourly_forecast` | Temperature and apparent temperature (°C), humidity, precipitation probability and cloud cover (%), precipitation (mm), wind speed at 10 m and 80 m and gusts (m/s), wind direction (deg), shortwave, direct and diffuse radiation (W/m²), `weather_code` and `weather_label`, derived indices | `location_id`, `weather_model`, `retrieved_at`, `forecast_time` |

`forecast_time` is the API's hourly time stamp in UTC (`timestamp with time
zone`; the API is asked for GMT). `retrieved_at` is the run time in UTC, cut to the
minute, so every run adds a new forecast. `weather_model` is always
`dwd_icon`. `hourly_forecast` is made a TimescaleDB hypertable on
`forecast_time` when possible.

The derived columns are `heating_degree_18c` = max(18 − T, 0),
`cooling_degree_22c` = max(T − 22, 0), `solar_generation_index` = shortwave
radiation / 1000 clipped to 0..1, `wind_generation_index` = (wind speed at
80 m / 12)³ capped at 1, `renewables_weather_index` = 0.55 wind + 0.45 solar
index, and `load_weather_index` = heating degree + 0.75 cooling degree.

Views: `latest_hourly_forecast` (newest forecast per location and hour,
enabled locations only), `latest_country_hourly_forecast` (weighted by
`aggregation_weight` per country) and `price_forecast_weather_features` (the
country view with `market_area`, `DE` mapped to `DE_LU`, and
`delivery_start_utc`). Each run updates the row of `weather` in
`public.metadata`.

## Configuration

```yaml
weather_forecast:
  enable: false
  schema_name: weather
  database_uri: postgresql://opendata:opendata@127.0.0.1:6432/opendata?options=--search_path=
  description: Crawls hourly DWD ICON weather forecasts for weather and energy-weather
    dashboards
  schedule: 15 */3 * * *
  forecast_hours: 120
  past_hours: 24
```

`locations` replaces the built-in location list; each entry needs
`location_id`, `name`, `country_code`, `country_name`, `region`,
`location_type`, `latitude` and `longitude`, and may set `aggregation_weight`
(default 1.0) and `enabled`. `request_timeout_seconds` (default 45) and
`user_agent` set the HTTP request.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl weather_forecast
```

## Notes

- Requests are retried up to five times with growing pauses, because
  Open-Meteo answers 503 when overloaded. A location that still fails is
  logged and skipped; the run fails only when no location returns data.
- The day-ahead price forecast in `packages/post` reads
  `weather.price_forecast_weather_features` (or
  `weather.latest_country_hourly_forecast`) as weather covariates.
