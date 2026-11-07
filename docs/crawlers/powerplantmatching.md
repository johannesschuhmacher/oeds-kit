# powerplantmatching

European power plant list from PyPSA
[powerplantmatching](https://github.com/PyPSA/powerplantmatching), read from
`powerplants.csv` on the project's `master` branch. The crawler also derives a
lookup from ENTSO-E EIC codes to plant coordinates.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/powerplantmatching.py` |
| Schema | `powerplantmatching` |
| Access | none |
| Licence | MIT |
| Resolution | snapshot (one row per plant) |
| Dashboard | `Crawlers/powerplantmatching.json` |

## Data

| Table | Content | Key |
| --- | --- | --- |
| `powerplants` | One row per plant: `name`, `fuel_type`, `technology`, `set_type`, `country`, `capacity`, `efficiency`, `date_in`, `date_retrofit`, `date_out`, `lat`, `lon`, `duration`, `volume_mm3`, `dam_height_m`, `storage_capacity_mwh`, `eic_code`, `project_id` | `source_id` (primary key) |
| `eic_geo_location` | `lat`, `lon` per EIC code | `eic_code` (deduplicated, indexed) |

`powerplants` keeps the powerplantmatching columns under snake-case names
(`Fueltype` becomes `fuel_type`, `id` becomes `source_id`, `EIC` becomes
`eic_code`, `projectID` becomes `project_id`). The code does not state the unit
of `capacity`; the other units are given by the column names (`volume_mm3`,
`dam_height_m`, `storage_capacity_mwh`). The `date_*` columns are numbers.

`eic_geo_location` takes the codes listed under `'ENTSOE'` in `project_id` and
the codes in `eic_code`, and adds the child codes from
`packages/crawler-pack/src/crawler/data/mapping_p_to_g.json` with the coordinates of their parent. Each
run also updates the row of `powerplantmatching` in `public.metadata`.

## Configuration

```yaml
powerplantmatching:
  enable: false
  schema_name: powerplantmatching
  database_uri: postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=
  description: Crawls power system and power plant data from PyPSA
  schedule: 0 4 * * 0
```

The crawler reads no further config keys; the source URL is fixed in the code.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl powerplantmatching
```

## Notes

- Rows without `lat` or `lon` are dropped, and duplicate `source_id` values
  are reduced to the first row.
- `powerplants` is upserted on `source_id` in batches of 5000, so plants
  that disappear from the source stay in the table. `eic_geo_location` is
  replaced on every run.
- The ENTSO-E availability map built after `entsoe_files` joins
  `powerplantmatching.powerplants`.
- Errors while downloading, writing or building the EIC mapping are logged,
  but the run does not fail.
