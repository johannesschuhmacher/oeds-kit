# ENTSOG

Reference data of the European gas transmission network and hourly physical
flows, allocations and firm technical capacities from the
[ENTSOG transparency platform API](https://transparency.entsog.eu/api/v1/).

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/entsog.py` |
| Schema | `entsog` |
| Access | none |
| Licence | ENTSOG terms of use (https://www.entsog.eu/privacy-policy-and-terms-use) |
| Resolution | 1 hour requested (`periodType=hour`) for the operational data |
| Dashboard | `Crawlers/entsog.json` |

## Data

Columns are the API fields in lower case (e.g. `operatorkey`, `pointlabel`,
`periodfrom`, `periodto`, `value`).

| Table | Content | Key |
| --- | --- | --- |
| `operators`, `connectionpoints`, `balancingzones`, `operatorpointdirections`, `interconnections`, `aggregateinterconnections` | Reference data of the API endpoints of the same name | none |
| `physical_flow` | Indicator `Physical Flow` | `id` |
| `allocation` | Indicator `Allocation` | `id` |
| `firm_technical` | Indicator `Firm Technical`, plus `index` (numeric copy of `value`) | `id` |

The operational tables are loaded with `periodType=hour`. `periodfrom` and
`periodto` are converted to UTC and stored with time zone. `id` is the record
id of the API; it is indexed, not a database constraint. Each run also updates
the row of `entsog` in `public.metadata`.

## Configuration

```yaml
entsog:
  enable: false
  schema_name: entsog
  description: Crawls ENTSOG transparency platform reference and operational gas data
  schedule: 30 2 * * *
  default_start_date: '2024-01-01'
  chunk_days: 1
  request_pause_seconds: 1.0
```

`default_start_date` (default `2024-01-01`) sets where an empty table starts.
`chunk_days` (default 7) is the number of days per request and
`request_pause_seconds` (default 1.0) the pause between requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl entsog
```

## Notes

- Reference tables are replaced on each run; an empty answer keeps the old
  table.
- Each operational table continues one day before its newest `periodfrom` and
  loads up to tomorrow (UTC). Returned records replace stored records with the
  same `id`, because the API returns gas days (06:00 to 06:00 local time) and
  long-valid firm technical capacities in every chunk.
- Requests are retried on HTTP 429 and 5xx.
