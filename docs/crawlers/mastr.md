# MaStR

Units, operators and catalogues of the German Marktstammdatenregister from its
[full data export](https://www.marktstammdatenregister.de/MaStR/Datendownload)
(Gesamtdatenexport). The crawler loads every XML file of the export ZIP into
one table per file type.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/mastr.py` |
| Schema | `mastr` |
| Access | none |
| Licence | DL-DE/BY-2-0 |
| Resolution | snapshot of the current full export |
| Dashboard | `Crawlers/mastr.json` |

## Data

The table name is the XML file name up to the first `_`: `EinheitenWind_1.xml`
and `EinheitenWind_2.xml` both go into `EinheitenWind`. The set of tables
follows the export. Columns are the XML element names, with `MaStR` written
as `Mastr`; values are not converted.

| Table | Content | Key |
| --- | --- | --- |
| `EinheitenSolar`, `EinheitenWind`, `EinheitenBiomasse`, `EinheitenWasser`, `EinheitenVerbrennung`, `EinheitenStromSpeicher`, ... | Units per technology | first key column found (see below) |
| `Katalogkategorien`, `Katalogwerte` | Catalogue categories and values that coded columns refer to | first key column found |
| `Ertuechtigungen` | Upgrades, several per plant | `Id` |
| `EinheitenAenderungNetzbetreiberzuordnungen` | Change log of grid operator assignments | none |
| other export tables | e.g. EEG, KWK and grid connection point data | first key column found |

Key: the first of `MastrNummer`, `EinheitMastrNummer`, `EegMastrNummer`,
`KwkMastrNummer`, `NetzanschlusspunktMastrNummer`, `Id`, `GenMastrNummer` that
the table has. After the import the crawler adds it as primary key if the
table has none. Tables without such a column, and
`EinheitenAenderungNetzbetreiberzuordnungen`, have no key. Each run also
updates the row of `mastr` in `public.metadata`.

## Configuration

```yaml
mastr:
  enable: false
  schema_name: mastr
  # Schedules are in UTC. The daily export is published in the German early
  # morning; at 04:00 UTC (05:00 CET in winter) it was not yet downloadable.
  schedule: 0 7 * * *
  base_download_url: https://download.marktstammdatenregister.de/Gesamtdatenexport
```

`base_download_url` is required. `tables` (a list of table names) restricts the
import, `max_rows_per_table` loads only the first rows of each table (for
tests), and `request_timeout_seconds` (default 90) sets the HTTP timeout. The
ZIP is stored in `$OEDS_CRAWLER_DATA_DIR` (default `crawler/data`).

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl mastr
```

## Notes

- The crawler reads the download page and takes the first link that starts
  with `base_download_url`, so it always loads the current export.
- Download once, then read from disk: each run downloads the whole ZIP
  (about 3 GB) to `mastr_export.zip`, reads the XML files from there and
  deletes the file afterwards. A broken connection is resumed with a range
  request after 120 s, up to 6 attempts; HTTP 429 and 5xx are retried with
  growing waits. A previous run's file is not reused.
- Tables with a key: rows whose key appears in the new export are deleted and
  written again. Rows that are no longer in the export stay in the table.
- Tables without a key: the first file of the table in a run empties the table,
  later files of the same run append. So these tables are replaced on each run.
- A new column in the export is added to the table; a numeric column that now
  holds text is changed to `TEXT`.
