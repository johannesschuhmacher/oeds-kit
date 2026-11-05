# Copernicus CDS

Downloads one configured request from the
[Copernicus Climate Data Store](https://cds.climate.copernicus.eu/)
([API how-to](https://cds.climate.copernicus.eu/en/how-to-api)) with
`cdsapi`. The file stays on disk; the database holds the request log and
summary statistics per variable.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/copernicus_cds.py` |
| Schema | `copernicus_cds` |
| Access | CDS Personal Access Token `COPERNICUS_CDS_KEY` (API URL `COPERNICUS_CDS_URL`, default `https://cds.climate.copernicus.eu/api`); the dataset terms must be accepted in the CDS portal |
| Licence | not stated; `public.metadata` records "Copernicus CDS dataset-specific license and terms" |
| Resolution | set by the request; the default request has the times 00:00, 06:00, 12:00 and 18:00 of one day |
| Dashboard | `Crawlers/copernicus_cds.json` |

## Data

Without `dataset` and `request` in the config, the crawler requests
`reanalysis-era5-single-levels` (`product_type` `reanalysis`) with
`2m_temperature`, `10m_u_component_of_wind`, `10m_v_component_of_wind` and
`surface_solar_radiation_downwards` for the 1st of the month that was 45 days
ago, `area` `[55.2, 5.5, 47.2, 15.5]`, as NetCDF.

| Table | Content | Key |
| --- | --- | --- |
| `requests` | `dataset`, `request_json`, `status` (`running`, `completed`, `failed`), `target_path`, `requested_at`, `completed_at`, `error` | `request_id` |
| `downloaded_files` | `dataset`, `target_path`, `file_size_bytes`, `fetched_at` | `request_id` |
| `variable_statistics` | Per NetCDF variable: `observations`, `min_value`, `mean_value`, `max_value` and `unit` (the variable's `units` attribute) | `request_id`, `variable` |
| `access_status` | Whether a token is configured | `source_name` |

`request_id` is a SHA-256 hash of dataset and request, so the same request
overwrites its row and its file. The view `file_summary` counts files and
bytes per `dataset`. Timestamps are stored with time zone. Each run also
updates the row of `copernicus_cds` in `public.metadata`.

## Configuration

```yaml
copernicus_cds:
  enable: false
  schema_name: copernicus_cds
  description: Downloads configured Copernicus Climate Data Store requests using cdsapi
  schedule: 35 3 * * 0
  storage_dir: crawler/data/copernicus_cds
```

`dataset` and `request` (a mapping in the form `cdsapi` expects) replace the
default request; both must be set. `target_suffix` (default `.nc`) is the
file ending. `cds_url` and `cds_key` override the environment variables.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl copernicus_cds
```

## Notes

- Files are written to `<storage_dir>/<dataset>_<first 12 characters of
  request_id><target_suffix>`. `storage_dir` is relative to the working
  directory `/app`; in the deployment `/app/crawler/data` is bind-mounted from
  the runtime directory.
- If the CDS delivers a zip, the NetCDF files in it are unpacked into a folder
  of the same name without suffix and summarised one by one.
- Without a token the run writes `access_status` and ends as skipped.
- The default request changes once a month, so the weekly runs in between
  download the same month again.
