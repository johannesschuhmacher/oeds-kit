# SMARD

Electricity generation, consumption and day-ahead prices for Germany from
[SMARD](https://www.smard.de/), the market data portal of the Bundesnetzagentur.
SMARD publishes much of the German ENTSO-E data under an open licence.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/smard.py` |
| Schema | `smard` |
| Access | none |
| Licence | CC BY 4.0 |
| Resolution | 15 minutes |
| Dashboard | `Crawlers/smard.json` |

## Data

The crawler loads eleven generation series (per energy source), the realised
consumption and the day-ahead price for the bidding zone DE-LU from the SMARD
chart files (`chart_data/<id>/DE/<id>_DE_quarterhour_<week start>.json`).

| Table | Content | Key |
| --- | --- | --- |
| `smard` | `mwh` per 15 minutes for each `commodity_id` and `commodity_name` (e.g. 4068 Photovoltaik, 410 Realisierter Stromverbrauch) | `timestamp`, `commodity_id` |
| `prices` | Day-ahead price `price` in EUR/MWh (`commodity_id` 4169) | `timestamp`, `commodity_id` |

Both tables are TimescaleDB hypertables. `timestamp` is the start of the
interval in UTC, stored without time zone. Each run also updates the row of
`smard` in `public.metadata` (source, licence, covered period).

## Configuration

```yaml
smard:
  enable: false
  schema_name: smard
  schedule: 0 4 * * *
  post_run_scripts: null
```

`default_start_date` (default `2024-06-02 22:00:00`, UTC) sets where an empty
table starts.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl smard
```

## Notes

- Each run continues after the newest stored timestamp of each series and
  loads one weekly file per series and pass until it is up to date. A first
  run from the default start date takes a few minutes.
- SMARD weeks start on Monday, German local time; the crawler follows the
  clock changes and drops the duplicate hour in October.
- Requests are paused by 0.5 s and retried, because smard.de resets
  connections when requests come too fast.
