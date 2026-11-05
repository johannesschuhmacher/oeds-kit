# GIE AGSI/ALSI

Daily gas storage (AGSI) and LNG terminal (ALSI) data from the
[GIE transparency platform API](https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf),
for the EU aggregate and Germany.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/gie_agsi_alsi.py` |
| Schema | `gie_agsi_alsi` |
| Access | API key `GIE_API_KEY` (free AGSI/ALSI account), sent as `x-key` header |
| Licence | not stated (the metadata refers to the GIE AGSI/ALSI platform terms) |
| Resolution | gas day |
| Dashboard | `Crawlers/gie_agsi_alsi.json` |

## Data

The default queries are AGSI and ALSI, each with `type=eu` (scope `EU`) and
`country=DE` (scope `DE`), from `https://agsi.gie.eu/api` and
`https://alsi.gie.eu/api`.

| Table | Content | Key |
| --- | --- | --- |
| `daily_inventory` | AGSI: `gas_in_storage`, `consumption`, `consumption_full`, `injection`, `withdrawal`, `working_gas_volume`, `injection_capacity`, `withdrawal_capacity`, `full_pct`; ALSI: `lng_inventory_gwh`, `lng_inventory_thousand_m3`, `lng_storage_capacity_gwh`, `lng_storage_capacity_thousand_m3`, `lng_send_out_gwh_per_day`, `lng_send_out_capacity_gwh_per_day`; plus `name`, `url`, `status`, `trend`, `fetched_at`, `payload_json`, `record_key` | `platform`, `scope`, `code`, `gas_day_start` |
| `latest_inventory` | View: newest `gas_day_start` per `platform`, `scope`, `code` | |
| `access_status` | Whether the API key is configured | `source_name` |

`platform` is `agsi` or `alsi`. `code` is the API `code`, or else its `url`,
`name` or the scope. `gas_day_start` is the date of the API field
`gasDayStart`. Values are stored as the API delivers them; the AGSI columns
are not converted, the ALSI columns carry the unit in their name.
`fetched_at` is the UTC time of the run; `payload_json` holds the full API
record. Each run also updates the row of `gie_agsi_alsi` in `public.metadata`.

## Configuration

```yaml
gie_agsi_alsi:
  enable: false
  schema_name: gie_agsi_alsi
  description: Crawls GIE AGSI gas storage and ALSI LNG data via x-key API access
  schedule: 20 5 * * *
  lookback_days: 30
```

`lookback_days` (default 30) sets the date window, from today minus
`lookback_days` to today (UTC). The API key comes from `api_key` or the
environment variable `GIE_API_KEY` in the crawler `.env`. `queries` replaces
the default queries (`platform`, `scope`, `params`), `page_size` (default 300)
sets the page size, `request_pause_seconds` (default 0.4) the pause between
pages, and `user_agent` and `request_timeout_seconds` (default 90) the HTTP
settings.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl gie_agsi_alsi
```

## Notes

- Without an API key the crawler only writes `access_status` (status
  `missing_credentials`) and the run is reported as skipped.
- Each run deletes the rows of the date window per `platform` and `scope` and
  writes the new rows, so revised values replace old ones.
- A failing query is logged and the other queries are still written; the run
  then ends as failed.
