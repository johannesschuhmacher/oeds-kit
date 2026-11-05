# Netztransparenz

Balancing, renewable actuals and spot price data of the German transmission
system operators from the WebAPI of
[Netztransparenz](https://www.netztransparenz.de/)
([API documentation](https://www.netztransparenz.de/xspproxy/api/staticfiles/ntp-relaunch/dokumente/web-api/dokumentation-webserviceapi-netztransparenz_v1.21.pdf)).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/netztransparenz.py` |
| Schema | `netztransparenz` |
| Access | OAuth2 client credentials `NETZTRANSPARENZ_CLIENT_ID`, `NETZTRANSPARENZ_CLIENT_SECRET` |
| Licence | not stated; `public.metadata` records "Netztransparenz WebAPI terms; review upstream terms before republication" |
| Resolution | as published per endpoint |
| Dashboard | `Crawlers/netztransparenz.json` |

## Data

By default the crawler reads seven CSV endpoints under
`https://ds.netztransparenz.de/api/v1/data/<path>/<from>/<to>`:
`nrv_saldo_minute` (`NrvSaldo/nrvSaldoMinute/Betrieblich`),
`nrv_saldo_operational` (`NrvSaldo/NRVSaldo/Betrieblich`),
`rebap_quality_assured` (`NrvSaldo/reBAP/Qualitaetsgesichert`),
`mFRR_satisfied_demand` (`NrvSaldo/mFRRSatisfiedDemand/Betrieblich`),
`online_solar_actuals` (`hochrechnung/Solar`),
`online_wind_onshore_actuals` (`hochrechnung/Windonshore`) and
`spot_market_prices` (`Spotmarktpreise`).

| Table | Content | Key |
| --- | --- | --- |
| `normalized_values` | One `value` per row and value column, with `timestamp_from`, `timestamp_to`, `category` (Datenkategorie), `data_type` (Datentyp), `unit` (Einheit), `area` (column name without the bracketed unit or direction), `direction` (`positive`/`negative` from the column name) and `status` | none; each run replaces the endpoint's rows in the requested window |
| `raw_rows` | Every CSV row as JSON (`payload_json`) | `endpoint_id`, `fetched_at`, `row_number` |
| `endpoint_runs` | One row per endpoint and run: window, HTTP status, row count, URL, error | `endpoint_id`, `fetched_at` |
| `access_status` | Whether credentials are configured | `source_name` |

The views `latest_values` (newest value per `endpoint_id`, `area`,
`direction`) and `endpoint_summary` (rows and covered period per endpoint)
read `normalized_values`. All timestamps are stored with time zone, in UTC.
`timestamp_from` and `timestamp_to` are built from Datum, von and bis and the
CSV's Zeitzone columns: UTC stays UTC, MEZ/CET and MESZ/CEST get a fixed offset
of +1 h and +2 h, other values are read as Europe/Berlin (an ambiguous hour
becomes empty). Each run also updates the row of `netztransparenz` in
`public.metadata`.

## Configuration

```yaml
netztransparenz:
  enable: false
  schema_name: netztransparenz
  description: Crawls Netztransparenz WebAPI datasets via OAuth2 client credentials
  schedule: 10 * * * *
  lookback_days: 7
  request_pause_seconds: 0.6
```

`endpoints` replaces the default list; each entry has `id`, `label`, `path`,
`format` (`csv`, or `json`, which is stored in `raw_rows` only) and optionally
`use_date_path: false` to omit the window from the URL. `default_start_date`
(UTC) can only shorten the window, which never starts more than
`lookback_days` back. `client_id` and `client_secret` override the
environment variables; `request_timeout_seconds` (default 60) and
`user_agent` set the HTTP client.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl netztransparenz
```

## Notes

- Without credentials the run writes `access_status` and ends as skipped.
- The crawler checks `https://ds.netztransparenz.de/api/v1/health` before the
  endpoints. A failing endpoint is logged in `endpoint_runs`, the others still
  run, and the run then fails.
- Requests are retried up to six times with growing waits (up to 120 s),
  because the API resets connections for seconds at a time.
- The ids `online_solar_actuals` and `online_wind_onshore_actuals` were kept
  when the `onlinehochrechnung/*` paths disappeared (404 since 2026-10); they
  now read the 15-minute `hochrechnung/*` feed.
