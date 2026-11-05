# regelleistung.net

Tender results and maximum exchange limits of the balancing products FCR,
aFRR and mFRR from the public datacenter of
[regelleistung.net](https://www.regelleistung.net/en-us/Data/Where-can-I-find-what-data).
The crawler lists the tender files of the API
`https://www.regelleistung.net/apps/crds/api/v2` and imports the Excel
workbooks.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/regelleistung.py` |
| Schema | `regelleistung` |
| Access | none |
| Licence | not stated; `public.metadata` records "Public regelleistung.net data; review upstream terms before republication" |
| Resolution | as in the tender files |
| Dashboard | `Crawlers/regelleistung.json` |

## Data

Each run lists the files of the last `lookback_days` (product types `FCR`,
`aFRR`, `mFRR`; markets `CAPACITY`, `ENERGY`; file types `RESULTS`,
`MAXIMUM_EXCHANGE_LIMIT`) and downloads at most `max_files_per_run` of them.

| Table | Content | Key |
| --- | --- | --- |
| `tender_files` | File list: `control_block`, `date_range_type`, `file_type`, `product_type`, `market`, `date_range`, `source_url`, `discovered_at` | `file_name` |
| `file_rows` | Every workbook row as JSON (`payload_json`), per sheet | `file_name`, `sheet_name`, `row_number`, `fetched_at` |
| `numeric_values` | One `value` per row and numeric column; `measure` is the column header, `delivery_date`, `product_type` and `market` come from the row | none; each import replaces the file's rows |
| `access_status` | Access model (public, no credentials) | `source_name` |

The views `file_summary` (files per `product_type`, `market`, `file_type`) and
`latest_numeric_values` (newest value per `product_type`, `market`, `measure`)
read these tables. `delivery_date` is the first parsable value of a date
column (header normalised to `delivery_date`, `date`, `date_from`,
`date_to`, `lieferdatum` or `ausschreibungstag`); values without time zone are
stored as UTC. `unit` is always empty. Timestamps are stored with time
zone. Each run also updates the row of `regelleistung` in `public.metadata`.

## Configuration

```yaml
regelleistung:
  enable: false
  schema_name: regelleistung
  description: Crawls public regelleistung.net datacenter tender files
  schedule: 30 4 * * *
  lookback_days: 35
  max_files_per_run: 12
  download_files: true
```

`product_types`, `markets` and `file_types` (lists) override the filters of
the file list, `page_size` (default 1000) its length. `download_files: false`
only updates `tender_files`. `request_timeout_seconds` (default 90) and
`user_agent` set the HTTP client.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl regelleistung
```

## Notes

- The window covers whole UTC days, from `lookback_days` before today to
  today.
- The crawler downloads the first `max_files_per_run` files in the order the
  API returns them, also when they were imported before, and re-imports them.
- A file that fails to download or parse is logged; the other files still
  run, and the run then fails.
