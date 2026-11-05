# PRISMA Capacity

Generic importer for JSON resources of the
[PRISMA Capacity Platform API](https://help.prisma-capacity.eu/solutions/shipper-hub-prisma-api-business-information).
PRISMA offers its API as paid packages; the crawler stores the raw records of
the resources listed in the config once a subscribed base URL and token are
set.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/prisma_capacity.py` |
| Schema | `prisma_capacity` |
| Access | PRISMA API package subscription (`PRISMA_API_BASE_URL`, `PRISMA_API_TOKEN`) |
| Licence | PRISMA API package terms, subscription-specific |
| Resolution | not stated (depends on the resource) |
| Dashboard | none |

## Data

For each configured resource the crawler sends one GET request to
`<base URL>/<path>` with the bearer token and stores every record of the JSON
answer as one row. A list is taken as is; from an object it takes `data`,
`items` or `value`, otherwise the object itself.

| Table | Content | Key |
| --- | --- | --- |
| `raw_resources` | `payload_json` (one record as compact JSON), `source_url`, `record_key` (SHA-256 of resource, row number and record) | `resource_id`, `fetched_at`, `row_number` |
| `access_status` | Whether credentials are configured (`requires_subscription` or `configured`) | `source_name` |

`fetched_at` is the request time in UTC (`timestamp with time zone`). Rows
are appended; each run adds a new snapshot. The view `resource_summary`
counts rows and the last fetch per `resource_id`. Each run with credentials
updates the row of `prisma_capacity` in `public.metadata`.

## Configuration

```yaml
prisma_capacity:
  enable: false
  schema_name: prisma_capacity
  description: Imports configured PRISMA Capacity Platform API resources after API
    package subscription
  schedule: 0 6 * * *
  resources: []
```

Each entry of `resources` needs an `id` and a `path` and may set `params`
(query parameters). `api_base_url` and `api_token` can be set in the config
instead of the environment variables; the config wins.
`request_timeout_seconds` (default 90) and `user_agent` set the HTTP requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl prisma_capacity
```

## Notes

- Without base URL or token the crawler only writes the `access_status` row
  and ends as skipped (exit code 3).
- With the default `resources: []` a run with credentials imports nothing;
  the resource paths must match the booked API package.
- A failing resource is logged, the others are still written, and the run
  then fails with the list of failed resources.
