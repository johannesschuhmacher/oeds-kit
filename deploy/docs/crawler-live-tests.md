# Live crawler validation

This is a source-connectivity and database-ingestion test, not a guarantee that
every source, historical period, subscription or data field works. It tests
both implementations when the upstream and KIT names overlap: 21 KIT and 32
upstream implementations, rather than only the 47 winners in the merged registry.

## Run it

Run inside the Linux test VM as the normal Docker-enabled user, not with sudo.
Complete [the installation checks](testing.md) first; they build the
`oeds-test:runtime` image. Keep your source credentials in a private file outside
the deployment checkout. Do not put credentials in Git or paste them into logs.

From the deployment repository:

```bash
bash tools/test_live_crawlers.sh "$HOME/crawler.env" --source all
```

The script creates a **separate PostgreSQL container with no published port**,
uses a separate database for each implementation and overrides database
destinations from the environment file. It does not remove or change the normal
OEDS installation. Email notifications are disabled. The temporary environment
copy is deleted when the script exits; your original file is not deleted.

To repeat selected checks from empty test databases:

```bash
bash tools/test_live_crawlers.sh "$HOME/crawler.env" \
  --cases kit:smard kit:entsoe_api --reset
```

`--reset` here deletes only the selected databases in
`oeds-crawler-validation-db`. Do not start overlapping live-test batches.
Use `--timeout 900 --workers 1` for a large source. Each worker has a 2-GB memory
limit by default; `--memory 6g --cpus 6 --workers 1` raises it on a suitable VM. This is a test limit, not a statement
about the memory required by a full national archive. `--image` selects another
locally built modular runtime image. Workers normally use the invoking user's
UID:GID; `--user` can override it for a deliberate permissions comparison.

Results are in `$HOME/oeds-crawler-validation/logs/`: one private log and one
JSON result per implementation. A repeat replaces that implementation's previous
result. Nonempty metadata, access-status and static ENTSO-E lookup tables do not
count as ingestion. Errors, empty data and time/memory limits make the command
exit unsuccessfully. Review warnings and dataset coverage too: a successful exit
with some data cannot prove that every sub-dataset is complete.

The databases remain available for inspection:

```bash
docker exec -it oeds-crawler-validation-db psql -U opendata -d kit_smard
```

Working downloads inside worker containers are temporary. For example,
Copernicus statistics remain in PostgreSQL, but its test NetCDF file disappears
with the worker. This test is not a persistent download archive.

After reviewing the results, remove only the isolated validation database and
network if they are no longer needed. Keep private logs until the findings have
been resolved:

```bash
docker rm -f -v oeds-crawler-validation-db
docker network rm oeds-crawler-validation
```

## Coverage and limitations

- KIT crawlers use their real `run()` method with source credentials and bounded
  configuration. Ninja uses the real public ZIP archives, not smoke fixtures.
- Most temporal checks request one day or a short recent lookback. Upstream
  ENTSO-E requires at least two days; six German series are requested. Cross-border
  flows and individual plant histories are outside this particular check.
- ENTSO-E FMS imports one monthly package window for EnergyPrices and
  ActualTotalLoad plus its plant reference. It does not validate every FMS item.
- EPEX requests one recent day and all four supported dataset groups. Regelleistung
  needs a completed month in the discovery window; at most three files are read.
- Copernicus requests one temperature variable, time and small area; DWD CDC reads
  January for all three variables. Weather/Open-Meteo use one location. OSM uses
  a small Karlsruhe bounding box, not the whole country.
- The upstream generic incremental driver can ignore a requested start date on an
  empty database. Bounded checks call `crawl_from_to()` directly where available;
  ENTSOG calls its dated operational-data method. These are ingestion checks,
  not a scheduler compatibility claim for every legacy constructor.
- Large upstream archive importers without subset settings are stopped at the
  resource limits. Partial rows demonstrate progress, not a successful full run.
- This does not test SMTP delivery, accept dataset terms, create paid subscriptions
  or bypass source access restrictions. PRISMA and JAO need additional credentials.

## Initial baseline audit, 5 September 2026

This section is the historical unmodified-upstream baseline. See the follow-up
below for corrected implementations; failures here are not the current result
of a corrected crawler.

The run used the intern-test VM (CentOS Stream 10), PostgreSQL 18.3,
TimescaleDB 2.26.3, PostGIS and the installed Python 3.13 modular runtime.
The official core remains pinned to `38abf45139f332d59a198c1b0feb95016b323ee1`.
The local crawler pack fixes were tested in `oeds-test:live`; this image is a
local test image, not a published release. The tested crawler-pack revision is
`1e730815581d2e36033c563f69ec044b5954594f`.

The initial diagnostics ran as root in isolated containers, followed by a
normal-user pass with UID:GID `1000:1000`. The one exception is the full EPEX
archive import: that completed as root, followed by an incremental run and a
5,000-trade database rewrite as UID 1000. A full empty-database EPEX import as
UID 1000 has not been repeated.

**All 53 implementations were attempted. 26 completed with real data: 18 KIT
and 8 upstream. The other 27 did not complete successfully.** Specifically,
13 failed, two reached the memory limit, two returned no data, four timed out
without data and six timed out with partial data. This is not an all-green
release qualification. Some failures are missing prerequisites or bounded-test
limits rather than crawler defects.

Most KIT checks had a 240-second limit, most upstream checks a 90-second limit,
and successful full Ninja/EPEX imports had longer limits. Initial diagnostics
also used longer limits for several upstream archives. Counts below describe
the final checked databases; live sources can change between runs. Lookup,
metadata and access-status rows are excluded where indicated.

### KIT implementations

"Loaded" means the bounded import completed and data exists, not that every
dataset, field and historical period is correct. In particular, read the GIE
and SMARD qualifications below.

| Crawler | Result | Evidence or remaining issue |
| --- | --- | --- |
| `copernicus_cds` | Loaded | One NetCDF download and one variable-statistics record; real CDS credentials. |
| `dwd_cdc` | Loaded | 6,256 regional monthly rows, all three variables for January. |
| `eia` | Loaded | 540 API rows and 540 numeric values. |
| `energy_forecast_crawler` | Loaded | One wide 48-hour prediction record; CSV history writable as UID 1000. |
| `entsoe_api` | Loaded | 768 prices, 384 load forecasts and 1,152 wind/solar forecasts. |
| `entsoe_fms` | Loaded | 23,095 EnergyPrices, 19,751 ActualTotalLoad and 165,064 plant-reference rows. |
| `entsog` | Loaded | Physical flow, allocation and firm technical data; 554 operators, 788 connection points and other reference tables. |
| `epex_spot` | Loaded | 1,901,078 trades, 168 statistics, 506 indices and 960 auction records; see permissions qualification above. |
| `eurostat_crawler` | Loaded | 2,204 rows from `nrg_inf_epcrw`, year 2024. |
| `gie_agsi_alsi` | Loaded, incomplete mapping | Eight daily inventories for EU/DE; AGSI numeric values populated, ALSI raw payload retained but LNG numeric mapping incomplete. |
| `mastr` | Timeout, no data | No completed XML import within 240 seconds as UID 1000 or the earlier 360-second diagnostic; no small streaming subset available. |
| `netztransparenz` | Loaded | Seven endpoint runs, 5,596 raw rows and 3,812 normalized values. |
| `ninja` | Loaded | 929,184 rows across all three full public archives; exact upstream value comparison passed. |
| `open_meteo` | Loaded | 336 hourly rows for one location. The API/model returned more than a one-day window. |
| `osm_power` | Failed | Public Overpass endpoint returned HTTP 406 for the small Karlsruhe request. |
| `power_system_data` | Loaded | 165,064 plant-reference and 3,016 EIC geolocation rows. |
| `prisma_capacity` | No data, access prerequisite | Only subscription status stored; no PRISMA API credentials were available. |
| `regelleistung` | Loaded | 2,790 file rows and 14,694 numeric values; 35-day discovery window, at most three files. |
| `smard` | Loaded, stale metadata | 6,324 energy/load rows and 576 prices from 2026; metadata still advertises a 2024 coverage end. |
| `tradinghub` | Loaded | 225 report rows and 1,694 numeric report values. |
| `weather_forecast` | Loaded | 24 hourly records for Berlin; all 20 tested numeric weather/derived fields populated. |

### Official upstream implementations

These are the unmodified pinned core sources. An upstream failure is not a
claim that the corresponding KIT implementation failed. Conversely, a KIT
success does not validate an upstream implementation with the same name.

| Crawler | Result | Evidence or remaining issue |
| --- | --- | --- |
| `chargepoint` | Timeout, no data | Large station-grid request loop did not finish; no bounded subset was available. |
| `dwd` | Failed, prerequisite | Import requires external NUTS shape files; its legacy constructor also needs a NUTS matrix. |
| `e2watch` | Failed | API JSON decoding failed; 163 building lookup rows but no measurements. |
| `ecmwf_crawler` | Failed | Writes downloads under the installed package, denied for UID 1000. The root diagnostic also lacked `public.nuts`. |
| `eex` | Failed | Legacy constructor calls BaseCrawler without its required configuration argument; not a working scheduler entry point. |
| `entsoe_crawler` | Loaded | Six German series over two days: 193 prices and 192 rows in each other series. |
| `entsog` | Loaded | 11,088 allocations, 18,326 physical flows and 699 firm technical rows, plus four reference tables. |
| `eon_grid_fees` | Failed, prerequisite | Missing `public.plz`, which depends on NUTS/postcode preparation. |
| `eview` | Timeout, partial | 80,460 rows; the legacy driver did not finish within the bounded run. |
| `fernwaerme_preisuebersicht` | Loaded | 717 rows. |
| `frequency` | Timeout, partial | 1,317,600 rows; full historical download exceeds this check. |
| `gie_crawler` | Loaded | 329 rows across six AGSI/ALSI tables. |
| `instrat_pl` | Failed | Missing expected date column in the API response. |
| `iwugebaeudetypen` | Loaded | 370 building-type rows. |
| `jao_crawler` | Failed, access prerequisite | No JAO API key was available. |
| `jrc_idees` | Timeout, partial | 26,956 rows across 479 tables; full archive not completed. |
| `ladesaeulenregister` | Failed | Configured source download URL returned HTTP 404. |
| `londondatastore` | Timeout, partial | 3,000,000 rows; full archive not completed. |
| `mastr` | Timeout, no data | No completed archive import; the first diagnostic also encountered a connection reset. |
| `netztransparenz` | Timeout, partial | 541,152 rows; an earlier diagnostic received HTTP 500 on a solar forecast endpoint. |
| `ninja` | Loaded | 929,184 rows; all three archives completed as UID 1000 and matched KIT exactly. |
| `nrw_kwp_waermedichte` | No data | ZIP download failed, although the crawler returned exit code zero. |
| `nuts_mapper` | Failed | Package-local download path denied for UID 1000. As root, 1,798 geometries were stored before a postcode ZIP member-name mismatch. |
| `oep` | Timeout, no data | Large download (approximately 10 GB) did not finish; no full import validated. |
| `opec` | Failed | Source download failed. |
| `opsd` | Failed | Package-local `when2heat.db` is not writable as UID 1000; 37,279 capacity rows were already stored. Root diagnostic exceeded 2 GB when reading the full SQLite file. |
| `refit` | Memory limit | Container exceeded 2 GB before any rows were stored. |
| `regelleistung` | Timeout, partial | 5,178 FCR demand rows; legacy code ignores the requested historical bounds. |
| `smard` | Loaded | Seven tables with 24 rows each. |
| `synpro` | Loaded | 420,480 rows across 12 profiles. |
| `vea_industrial_load_profiles` | Memory limit | Container exceeded 2 GB before any rows were stored. |
| `windmodel` | Failed | Expected HTML element was absent; `None.find_all` raised an error. |

### Fixes verified during the run

- ENTSOG reference requests now include `limit=-1`: the operator table grows from
  the default 100 records to all 554 records returned by the source.
- The crawler package now includes the NetCDF backend needed by xarray.
  Copernicus authentication, download and temperature statistics were verified.
- EPEX trade CSVs are parsed and written in blocks. A 2-GB worker previously died
  before writing trades; the final streaming run completed all four data groups,
  including 1,901,078 trades, in 14 minutes 33 seconds under the same memory limit.
- SMARD computes chart weeks in the German calendar, including summer/winter
  time, rather than assuming that every week starts Sunday at 22:00 UTC.
  A Wednesday start date now produces real values instead of thirteen 404s.
- Energy Forecast writes CSV history into the existing runtime data directory,
  not into the installed package. The normal-user run confirmed the output.

All 14 focused regression tests passed locally and in the Linux runtime image.
The official core source was not changed to hide or work around its failures.

### Direct value checks

Both Ninja implementations imported 324,336 onshore rows, 324,336 offshore rows
and 280,512 solar rows. All **23,071,872 numeric values matched exactly**, and
all capacity factors were non-null and between zero and one.

The sampled ENTSO-E price, load and wind/solar forecast columns, SMARD values and
weather variables contained non-null numeric values. Copernicus statistics had
positive observation counts, ordered minimum/mean/maximum values and plausible
temperature values in kelvin. These checks do not establish all-provider
scientific equivalence. In particular, GIE ALSI payloads are retained but its
LNG-specific numeric fields are not mapped to the current AGSI-oriented columns.

An additional EPEX check rewrote 5,000 real trades as UID 1000 and verified
unchanged values and no duplicate records. A normal-user incremental run also
completed. This tests write permissions and upserts, not a second full download.

To repeat the full Ninja comparison after both imports:

```bash
docker run --rm --network oeds-crawler-validation --memory 2g --user "$(id -u):$(id -g)" \
  -v "$PWD/tests:/tests:ro,z" --entrypoint python oeds-test:runtime /tests/compare_ninja.py
```

### Remaining work

1. Map ALSI's LNG-specific numeric fields explicitly and update SMARD's metadata
   coverage from the actual import. Stored data alone does not resolve these gaps.
2. Diagnose the Overpass HTTP 406 response without bypassing source restrictions.
   Supply PRISMA/JAO credentials only if these licensed sources are required.
3. Provide a bounded or streaming MaStR path and verify a complete XML import.
   Repeat large upstream archives with suitable disk, memory and runtime budgets.
4. Fix upstream runtime paths, changed download URLs/API formats and legacy
   constructor prerequisites in focused core contributions; then retest them.
5. Repeat a full empty-database EPEX run as the normal runtime user. Extend
   numeric/reference comparisons beyond Ninja before claiming full equivalence.

### Isolation and cleanup

The normal six-service intern-test installation was not reinstalled or updated
by this audit. Its runtime `.env` was not overwritten. The local source `.env`
remains unchanged. The temporary VM credential copies were removed; the wrapper
was checked both with successful imports and a failing EEX run, and removed its
temporary copy on both exits. The isolated databases and private redacted logs
remain for inspection. They are not included in Git.

This VM runs CentOS Stream 10. These results do not constitute a fresh Ubuntu
installation test, a repeat of scheduler/post-script tests or a Grafana audit.

## Follow-up fixes, 5 September 2026

The test core is based on official OEDS, with focused corrections
in `johannesschuhmacher/oeds-core` at `8a53778` (runtime fixes at `113a6f2`,
followed by a CI-only dependency correction). It is not an upstream release.
The crawler pack is `2f77898`. Their revisions are pinned in `compatibility.yml`.
All follow-up workers used UID:GID 1000:1000. Large checks used one worker,
6 GB and six CPUs on the 12-GB/eight-CPU intern-test host. The database was
isolated from the installed stack. Full national archives are not certified.

| Implementation | Follow-up evidence |
| --- | --- |
| KIT GIE | Eight inventory rows, including four ALSI records with numeric GWh, thousand m3 and GWh/day fields. Repeated imports passed. An old-schema upgrade preserved rows and an existing dependent view. |
| KIT SMARD | 6,971 stored records; metadata exactly matches stored temporal bounds. Fresh and repeated imports passed. |
| KIT MaStR | 100 rows each from EinheitenWind, Katalogkategorien and Katalogwerte. HTTP range ZIP reading and bounded XML parsing complete without loading the 3-GB archive into memory. Repeating the import leaves 300 rows, without duplicate primary keys. |
| KIT EPEX | Full empty-database import as UID 1000 completed in 881 seconds: 1,901,078 trades, 168 statistics, 506 indices and 960 auction records. This closes the earlier normal-user qualification. |
| Core NUTS/postcodes | 1,798 geometries and 8,334 postcodes loaded. Writable runtime cache, nested ZIP member and leading-zero postcodes fixed. |
| Core OPSD | 37,279 capacity rows and a 48-row when2heat sample. Writable cache and chunked SQLite reads replace the previous permission/memory failures. |
| Core REFIT | One house, 48 measurements; archive streamed to disk, CSV read in blocks. |
| Core VEA | Two profiles: 140,544 time-series values and two master records. Blocked reshaping also tested across multiple blocks with known values. |
| Core frequency | One 2011 file, 48 measurements; configurable bounds avoid an unbounded archive test. |
| Core JRC IDEES | One German workbook, 2,046 rows in 93 tables. |
| Core charging register | Current download discovered on the official page; 48 stations loaded, replacing the obsolete 404 URL. |
| Core London | One CSV, 48 measurements. |
| Core OEP | 48 demand areas via the documented API limit; no 10-GB full import or partial cache masquerading as a full download. |
| Core Regelleistung | Bounded day respected; 126 records in two FCR tables. Anonymous FCR results were empty for the requested day, so the three-table check remains partial. |

Together with the baseline successes, **36 of 53 implementations have completed
a real bounded ingestion: 19 KIT and 17 core**. This combines the inventory audit
with targeted follow-ups; it is not a new all-53 run on one image.
Eighteen crawler-pack regressions, three core regressions and nine deployment
tests pass. The core regression checks include exact VEA values, multi-block
when2heat reads and repeatable exclusive-end Regelleistung windows.

### Remaining limitations

- KIT OSM: Overpass returned HTTP 406 for a small query. No access restriction
  was bypassed. PRISMA and core JAO still need source credentials.
- Core EEX: constructor/configuration fixed, but its licensed local archive is
  absent. This is a different crawler from the successfully tested KIT EPEX.
- Core EON: real NUTS/postcode prerequisites now load; the Nominatim geocoding
  request timed out. No bulk geocoding retry was attempted.
- Core Instrat and Windmodel: direct requests returned HTTP 403. They now report
  HTTP errors instead of misleading parser exceptions. E2Watch still returns
  non-JSON content after correcting the building identifier index.
- Core DWD and ECMWF need additional legacy geographic/runtime preparation;
  ECMWF's package-local working path remains unresolved. Core chargepoint,
  MaStR, eview and Netztransparenz full imports remain outside the completed
  bounded tests. NRW heat-density and OPEC source failures remain open.
- Passing a sample does not certify all dates, all source fields, full-size
  resource use, email delivery or numerical equivalence of every crawler.

The application reset/reinstall and scheduler, post-script and Grafana results
are recorded separately in [VM installation results](test-results.md).

After a fresh GitHub assembly, all twelve corrected successful implementations
in the table above (excluding the separately completed EPEX run) were repeated
in `oeds-test:runtime`, UID 1000, with empty validation databases. All twelve
passed. Regelleistung was also repeated and remained partial (126 records,
two of three requested FCR datasets). This repeat used the published private
core and crawler revisions, not source files mounted from the development tree.
