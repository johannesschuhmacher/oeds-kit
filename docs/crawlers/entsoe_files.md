# ENTSO-E File Library

Load, generation, capacity, price, cross-border, balancing and outage data from
the File Library (FMS) of the
[ENTSO-E Transparency Platform](https://transparency.entsoe.eu/). The crawler
downloads the tab-separated extracts in `TP_export` from
`https://fms.tp.entsoe.eu` and writes one table per data item.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/entsoe_files.py` |
| Schema | `entsoe_files` |
| Access | Transparency Platform account: `ENTSOE_USERNAME`, `ENTSOE_PASSWORD` (OAuth2 password grant) |
| Licence | not stated |
| Resolution | per data item (`ResolutionCode` column) |
| Dashboard | `Crawlers/entsoe_files.json` |

## Data

Each data item is named without its extract version (`EnergyPrices_12.1.D`).
At run time the crawler uses the newest File Library folder of the item
(`_r3.2` before `_r3.1`). Units are part of the column names (`TotalLoad[MW]`).

| Table | Content | Key |
| --- | --- | --- |
| `ActualTotalLoad` | 6.1.A: `TotalLoad[MW]` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `DayAheadTotalLoadForecast` | 6.1.B: `TotalLoad[MW]` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `TotalLoadForecast` | 6.1.C_D_E: `MinimumLoadForecast[MW]`, `MaximumLoadForecast[MW]` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode`, `ContractType` |
| `UnavailabilityOfConsumptionUnits` | 7.1.A_B: planned, actual and total unavailable capacity `[MW]` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `YearAheadForecastMargin` | 8.1: `ForecastMargin[MW]` | `Year`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `ExpansionAndDismantlingProjects` | 9.1: grid projects, `NewNTC[MW]` | `DateTime(UTC)`, `OutAreaDisplayName`, `InAreaDisplayName`, `ProjectType`, `AssetCode`, `EstimatedCompletionDate` |
| `UnavailabilityInTheTransmissionGrid` | 10.1.A_B: outage events, `NewNTC[MW]` | `InstanceCode`, `Version`, `StartOutage(UTC)`, `EndOutage(UTC)`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `OutAreaCode`, `InAreaCode`, `Status`, `Type` |
| `UnavailabilityOfOffshoreGrid` | 10.1.C: outage events, `WindPowerFedIn[MW]`, `InstalledWindPowerGenerationCapacity[MW]` | `InstanceCode`, `Version`, `StartOutage(UTC)`, `EndOutage(UTC)`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `AssetCode`, `Status` |
| `ForecastedTransferCapacities` | 11.1: `ForecastTransferCapacity[MW]` per border | `DateTime(UTC)`, `ResolutionCode`, `OutAreaDisplayName`, `InAreaDisplayName`, `ContractType` |
| `UseOfTransferCapacity` | 12.1.A: `AllocatedCapacity[MW]`, `RequestedCapacity[MW]`, `CapacityPrice[Currency/MWh]` | `InstanceCode`, `DateTime(UTC)`, `ResolutionCode`, `ContractType`, `Category`, `Sequence`, `OutAreaDisplayName`, `InAreaDisplayName` |
| `TotalCapacityNominated` | 12.1.B: `Capacity[MW]` | `DateTime(UTC)`, `ResolutionCode`, `OutAreaDisplayName`, `InAreaDisplayName`, `ContractType` |
| `TotalCapacityAlreadyAllocated` | 12.1.C: `Capacity[MW]` | `InstanceCode`, `DateTime(UTC)`, `ResolutionCode`, `ContractType`, `Category`, `OutAreaDisplayName`, `InAreaDisplayName` |
| `EnergyPrices` | 12.1.D: `Price[Currency/MWh]` with `Currency` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `ContractType`, `Sequence` |
| `ImplicitAllocationsNetPositions` | 12.1.E: `NetPosition[MW]`, `Direction` | `DateTime(UTC)`, `ResolutionCode`, `AreaCode`, `AreaTypeCode`, `ContractType` |
| `CommercialSchedules` | 12.1.F: `DayAheadCapacity[MW]`, `TotalCapacity[MW]` per border | `DateTime(UTC)`, `ResolutionCode`, `OutAreaCode`, `InAreaCode` |
| `CommercialSchedulesNetPositions` | 12.1.F: `DayAheadCapacity[MW]`, `TotalCapacity[MW]` with directions | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `PhysicalFlows` | 12.1.G: `Flow[MW]` per border | `DateTime(UTC)`, `ResolutionCode`, `OutAreaDisplayName`, `InAreaDisplayName` |
| `RedispatchingInternal` | 13.1.A: `CapacityImpact[MWh/MTU]` | `InstanceCode`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `AssetCode`, `ActionType`, `ActionDirection` |
| `RedispatchingCrossBorder` | 13.1.A: `CapacityImpact[MWh/MTU]` | `InstanceCode`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `AssetCode`, `OutAreaCode`, `InAreaCode`, `ActionType`, `ActionDirection` |
| `Countertrading` | 13.1.B: `ChangeInCrossBorderExchange[MW]` | `InstanceCode`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `OutAreaCode`, `InAreaCode` |
| `CostsOfCongestionManagement` | 13.1.C: monthly redispatching, countertrading, other and total costs with `Currency` | `Year`, `Month`, `AreaCode`, `AreaTypeCode` |
| `InstalledGenerationCapacityAggregated` | 14.1.A: `AggregatedInstalledCapacity[MW]` per `ProductionType` | `Year`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode`, `ProductionType` |
| `InstalledGenerationCapacityPerProductionUnit` | 14.1.B: `InstalledCapacity[MW]`, `VoltageLevel[kV]` per production unit | `ProductionUnitCode`, `ValidityPeriodStart(UTC)`, `ValidityPeriodEnd(UTC)`, `ProductionType`, `AreaCode`, `AreaDisplayName`, `AreaTypeCode` |
| `DayAheadAggregatedGeneration` | 14.1.C: `GenerationForecast[MW]`, `ScheduledConsumption[MW]` | `DateTime(UTC)`, `AreaDisplayName`, `AreaTypeCode` |
| `GenerationForecastsForWindAndSolar` | 14.1.D: day-ahead, intraday and current forecast `[MW]` per `ProductionType` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `ProductionType`, `AreaTypeCode` |
| `UnavailabilityOfProductionAndGenerationUnits` | 15.1.A_B_C_D: outage events, `AvailableCapacity[MW]` | `InstanceCode`, `Version`, `StartOutage(UTC)`, `EndOutage(UTC)`, `StartTimeSeries(UTC)`, `EndTimeSeries(UTC)`, `AssetCode`, `Status`, `Type` |
| `ActualGenerationOutputPerGenerationUnit` | 16.1.A: `ActualGenerationOutput[MW]`, `ActualConsumption[MW]` per generation unit | `DateTime(UTC)`, `ResolutionCode`, `AreaCode`, `AreaDisplayName`, `AreaTypeCode`, `AreaMapCode`, `GenerationUnitCode`, `GenerationUnitName`, `GenerationUnitType` |
| `AggregatedGenerationPerType` | 16.1.B_C: `ActualGenerationOutput[MW]`, `ActualConsumption[MW]` per `ProductionType` | `DateTime(UTC)`, `ResolutionCode`, `AreaDisplayName`, `ProductionType`, `AreaTypeCode` |
| `AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants` | 16.1.D: `StoredEnergy[MWh]` | `Year`, `Month`, `Week`, `ResolutionCode`, `AreaDisplayName`, `AreaTypeCode` |
| `ImbalancePrices` | 17.1.G: positive and negative imbalance price components `[Currency/MWh]` | `DateTime(UTC)`, `ResolutionCode`, `AreaCode`, `AreaTypeCode` |
| `TotalImbalanceVolumes` | 17.1.H: `TotalImbalanceVolume[MWh]`, `Difference[MWh]` | `DateTime(UTC)`, `ResolutionCode`, `AreaCode`, `AreaTypeCode` |
| `ProductionAndGenerationUnits` | Master data of production and generation units, capacities `[MW]` | `ProductionUnitCode`, `GenerationUnitCode`, `ValidityPeriodStart(UTC)`, `ValidityPeriodEnd(UTC)`, `AreaCode`, `AreaDisplayName`, `AreaTypeCode` |
| `TransmissionAssets` | Master data of transmission assets, `InstalledCapacity[MW]`, `LossFactor` | `AssetCode`, `ValidityPeriodStart(UTC)`, `ValidityPeriodEnd(UTC)`, `AreaCode`, `AreaDisplayName`, `AreaTypeCode` |

The key is a unique constraint (`unique_...`); for `ProductionAndGenerationUnits`,
`TransmissionAssets` and `InstalledGenerationCapacityPerProductionUnit` it
treats NULLs as equal. Every table has `UpdateTime(UTC)` with an index
`ix_<table>_updatetime`. All `...(UTC)` columns are `timestamp with time zone`;
time stamps without zone in the files are read as UTC. Columns that ENTSO-E
adds later are added to the table automatically. The crawler does not write a
row in `public.metadata`.

## Configuration

```yaml
entsoe_files:
  enable: false
  schema_name: entsoe_files
  description: Crawls ENTSO-E File Library data (Transparency Platform File Library)
  default_start_date: '2014-01-01'
  post_run_scripts:
  - oeds-post gapfill entsoe-files
  - oeds-post refresh entsoe-availability-map
  jobs:
    latest_hourly:
      enable: false
      schedule: 0 * * * *
      mode: fms_package_refresh
      fms_package_window_months: 1
      fms_package_write_mode: full_upsert
      run_post_scripts: true
      target_data_items:
      - ActualTotalLoad_6.1.A_r3
      - DayAheadTotalLoadForecast_6.1.B_r3
      - GenerationForecastsForWindAndSolar_14.1.D_r3
      - EnergyPrices_12.1.D_r3
      - ForecastedTransferCapacities_11.1_r3
      - PhysicalFlows_12.1.G_r3
      - AggregatedGenerationPerType_16.1.B_C_r3
      - DayAheadAggregatedGeneration_14.1.C_r3
      - UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D
      - ActualGenerationOutputPerGenerationUnit_16.1.A
    revision_sweep_daily:
      enable: false
      schedule: 30 2 * * *
      mode: fms_package_refresh
      fms_package_window_months: 3
      fms_package_write_mode: full_upsert
      run_post_scripts: true
      target_data_items:
      - ActualTotalLoad_6.1.A_r3
      - DayAheadTotalLoadForecast_6.1.B_r3
      - GenerationForecastsForWindAndSolar_14.1.D_r3
      - EnergyPrices_12.1.D_r3
      - ForecastedTransferCapacities_11.1_r3
      - PhysicalFlows_12.1.G_r3
      - AggregatedGenerationPerType_16.1.B_C_r3
      - DayAheadAggregatedGeneration_14.1.C_r3
      - InstalledGenerationCapacityAggregated_14.1.A_r3
      - UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D
      - InstalledGenerationCapacityPerProductionUnit_14.1.B
      - ActualGenerationOutputPerGenerationUnit_16.1.A
    # Run once by hand (oeds-crawl entsoe_files --job initial_unit_data) before
    # enabling the jobs above: it loads the history from default_start_date.
    # Once a table exists, runs only load recent files. The availability map
    # and its dashboard need these unit data (generation: about 42 GB of files).
    initial_unit_data:
      enable: false
      run_post_scripts: true
      target_data_items:
      - UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D
      - InstalledGenerationCapacityPerProductionUnit_14.1.B
      - ActualGenerationOutputPerGenerationUnit_16.1.A
  gapfill:
    enable: false
    target_schema: entsoe_files_gapfilled
    method: donor_refined
    candidate_periods:
    - 24h
    - 7d
    donor_context_periods: 6
    donor_search_radius: 28d
    refinement_periods: 3
    max_gap_periods: 24
    lookback: 28d
    fail_on_table_error: true
    tables:
    - ActualTotalLoad
    - DayAheadTotalLoadForecast
    - GenerationForecastsForWindAndSolar
    - EnergyPrices
    - ForecastedTransferCapacities
    - PhysicalFlows
    table_methods:
      ActualTotalLoad: linear
      DayAheadTotalLoadForecast: donor_refined
      GenerationForecastsForWindAndSolar: donor_refined
      EnergyPrices: donor_refined
      ForecastedTransferCapacities: donor_refined
      PhysicalFlows: donor_refined
```

Keys the crawler reads:

- `default_start_date` (default `2014-01-01`, Europe/Berlin if no zone is
  given): where a run without package window starts.
- `target_data_items`: data items to load; a version suffix such as `_r3` is
  ignored, unknown names are logged. Without it, all 33 items are loaded.
- `fms_package_window_months`: load only the files of the current calendar
  month and the `n - 1` months before it (months in Europe/Berlin).
- `fms_package_write_mode: full_upsert`: upsert every row of these files by
  the table key.

`mode` is not read by the code. `gapfill` is read by the post-processing only.
Downloads go to `OEDS_CRAWLER_DATA_DIR` (`/app/crawler/data` in
`deploy/compose.yml`) and are deleted after each file.

Jobs (only the named jobs are scheduled):

- `latest_hourly`: every hour, the current month's files of the ten listed
  items.
- `revision_sweep_daily`: 02:30 every day, the files of the last three months
  of the same items plus the two installed-capacity items, to pick up
  revisions.
- `initial_unit_data`: run once by hand. It has no package window, so it loads
  the three unit-level items from `default_start_date`. It has no own
  `schedule` and would inherit `0 4 * * *` if enabled.

After a successful scheduled run of these jobs, `post_run_scripts` fill gaps
into `entsoe_files_gapfilled` and refresh the availability map (`packages/post`).

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl entsoe_files --job latest_hourly
docker exec oeds-scheduler oeds-crawl entsoe_files --job revision_sweep_daily
docker exec oeds-scheduler oeds-crawl entsoe_files --job initial_unit_data
```

Without `--job` the crawler loads all 33 data items from `default_start_date`.
`oeds-crawl` does not start the `post_run_scripts`.

## Notes

- Without package window, a missing table is created and filled from
  `default_start_date`. For an existing table with `UpdateTime(UTC)` values,
  only files of the last 90 days are read and only rows with an `UpdateTime`
  newer than the stored maximum are written.
- Monthly files are selected by the `YYYY` or `YYYY_MM` prefix of their name.
  The single-file items (installed capacities, production and generation units,
  transmission assets, year-ahead margin) and the items 9.1, 13.1.C and 16.1.D
  are read without date filter.
- An upsert rewrites a stored row only if the file has a newer
  `UpdateTime(UTC)` or the stored value is NULL.
- Columns renamed by ENTSO-E in the r3.1 extracts (October 2026) are renamed
  in existing tables, keeping the data.
- A run that fails for any file raises an error at the end, after all other
  files are processed.
