# Energy Arena submission

`oeds-post submit energy-arena` submits the OEDS day-ahead price forecast
(`oeds-post forecast day-ahead-price`, upstream LEAR) to the
[Energy Arena](https://energy-arena.org) benchmark. The forecast is still
written to the schema `price_forecast` as before; the submission only reads it.

## What is submitted

| Challenge | Content | Values |
| --- | --- | --- |
| 2: Day-Ahead Prices, DE_LU, point | the point forecast | one value per quarter-hour |
| 8: Day-Ahead Prices, DE_LU, quantile | the quantiles 2.5, 25, 50, 75 and 97.5 % | five values per quarter-hour |

A target is one calendar day in Europe/Berlin: 96 quarter-hours, 92 or 100 on
clock-change days, in EUR/MWh with two decimals, sent with `target_start` (local
midnight) to `POST https://api.energy-arena.org/api/v1/submissions`. The
deadline is 12:00 Europe/Berlin on the day before; the latest submission before
it counts.

The command takes the newest `completed` `day_ahead` run for tomorrow
(Europe/Berlin). It submits nothing (exit code 0) when the deadline has passed
or when `entsoe_api.day_ahead_prices` does not yet hold EXAA prices for the
whole target day. The model needs those prices and otherwise silently uses the
previous day's. It fails (exit code 1, alert mail) when the key is missing,
when no forecast run is newer than the EXAA prices, or when the API refuses
the submission.

The point forecast is the mean of the LEAR forecast (trained on the past 364
days) and the EXAA price of the target day (`PriceForecastConfig.train_days`
and `exaa_weight`). In a backtest from 1 October to 10 November 2026 this
lowered the mean daily RMSE from 18.4 (LEAR on 56 days, used until November
2026) to 17.0 EUR/MWh and the WIS from 9.0 to 8.2; EXAA alone had 18.8. The
quantiles are the point forecast shifted by quantiles of the SDAC - EXAA
differences of the past 56 days, not an error model of the forecast; offsets
from the forecast's own past errors or per hour of day did not score better.

Weather covariates (temperature, wind speed at 80 m and shortwave radiation,
German averages from `open_meteo`) enter only once the crawler's kept daily
runs cover the whole training window, with 364 days from about November 2027
on. For each delivery day the forecast takes the first run of the day before
(about 00:45 UTC), so training days and the target day see forecasts with the
same lead time. In the backtest these variables changed neither RMSE nor WIS
(17.06 instead of 17.04), because the ENTSO-E load, wind and solar forecasts
already carry the weather.

## Schedule

The job `energy_arena` of the crawler `entsoe_api` loads the ENTSO-E data, runs
the forecast and then submits it, at 09:40 and 10:40 UTC:

| | 09:40 UTC | 10:40 UTC | Deadline |
| --- | --- | --- | --- |
| Winter (CET) | 10:40, EXAA may still be missing | 11:40, submits | 11:00 UTC |
| Summer (CEST) | 11:40, submits | 12:40, too late, nothing submitted | 10:00 UTC |

EXAA prices appear in the ENTSO-E File Library around 11:10 Europe/Berlin
(09:10 UTC in summer, 10:10 UTC in winter). A run takes about three to four minutes
to the submission; the job skips the forecast's backtest (`--backtest-days 0`),
which would add about a minute per backtest day. A second submission on the same day replaces the
first. The daily forecast at 12:35 UTC
(`forecast_daily`) stays as it is and submits nothing.

```yaml
entsoe_api:
  jobs:
    energy_arena:
      enable: true
      schedule: 40 9,10 * * *
      lookback_days: 14
      lookahead_days: 2
      run_post_scripts: true
      post_run_scripts:
      - oeds-post forecast day-ahead-price --backtest-days 0
      - oeds-post submit energy-arena
```

Enable the job on one server only, otherwise every forecast is submitted twice.
At KIT, `iip-vm-oeds-intern` submits.

## Key

The API key is created in the [dashboard](https://energy-arena.org/dashboard)
and goes into `/open_energy_data_server/runtime/crawler/.env`:

```bash
ENERGY_ARENA_API_KEY="..."
ENERGY_ARENA_EMAIL="..."   # account of the key, not used by the code
```

The scheduler reads this file when its container starts. After changing it,
recreate the container:

```bash
cd /open_energy_data_server/repo/deploy && docker compose --profile crawlers up -d scheduler
```

Leaderboard and forecast visibility are set per challenge in the dashboard.

## Run by hand

```bash
docker exec oeds-scheduler oeds-post submit energy-arena --dry-run
docker exec oeds-scheduler oeds-post submit energy-arena --target-date 2026-11-08
```

`--dry-run` prints the payloads instead of submitting them and ignores the
deadline.

## Switch off

Set `enable: false` for the job `energy_arena` in
`/open_energy_data_server/runtime/CRAWLER_CONFIG.yml` (or on the configuration
tab in the admin UI). The scheduler rereads the file. To keep the early
forecast without submitting it, remove only the line
`oeds-post submit energy-arena`.
