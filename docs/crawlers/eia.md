# EIA

U.S. energy data from the
[EIA Open Data API](https://www.eia.gov/opendata/documentation.php)
(`https://api.eia.gov/v2`). The crawler runs a configurable list of API
routes and stores the rows in generic tables; by default it loads the hourly
fuel type data of the electricity route for the respondent `CAL`.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/eia.py` |
| Schema | `eia` |
| Access | API key `EIA_API_KEY` |
| Licence | not stated; `public.metadata` records "EIA open data terms; cite EIA as source" |
| Resolution | set by the request; hourly for the default request |
| Dashboard | `Crawlers/eia.json` |

## Data

The default request reads the route `electricity/rto/fuel-type-data/data/`
with `frequency` `hourly`, `data[0]` `value`, `facets[respondent][]` `CAL`,
sorted by `period` descending, for the last `lookback_days`.

| Table | Content | Key |
| --- | --- | --- |
| `api_rows` | Every API row as JSON (`payload_json`) with its `period` | `request_id`, `row_number`, `fetched_at` |
| `numeric_values` | One `value` per row and numeric field; `measure` is the field name, `dimension` joins the non-numeric fields (`key=value; ...`), `unit` is the row's `unit` or `units` field | none; each run replaces the request's rows |
| `access_status` | Whether an API key is configured | `source_name` |

The views `latest_values` (newest value per `request_id`, `dimension`,
`measure`) and `request_summary` (values and covered period per `request_id`
and `measure`) read `numeric_values`. `period` is the API's `period` parsed
as UTC and stored with time zone. Each run also updates the row of `eia` in
`public.metadata` (source, covered period).

## Configuration

```yaml
eia:
  enable: false
  schema_name: eia
  description: Crawls configured U.S. EIA Open Data API routes
  schedule: 55 * * * *
  lookback_days: 14
```

`requests` replaces the default list; each entry has `id`, `route` and
`params` (EIA query parameters), and optionally `page_size`, `max_rows` and
`use_default_date_window: false`. Without `start` or `end` in `params`, the
crawler sets them to the last `lookback_days` in whole UTC hours
(`YYYY-MM-DDTHH`). `page_size` (default 5000) and `max_rows_per_request`
(default 25000) apply to all requests. `api_key` overrides the environment
variable; `request_timeout_seconds` (default 90), `request_pause_seconds`
(default 0.2, between pages) and `user_agent` set the HTTP client.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl eia
```

## Notes

- Each run deletes all rows of a request and writes the new window, so the
  tables hold only the last `lookback_days`, not a growing history.
- Pages of `page_size` rows are read until a page is short or `max_rows` is
  reached.
- Without an API key the run writes `access_status` and ends as skipped.
