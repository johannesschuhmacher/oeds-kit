# Trading Hub Europe

Gas market reports of the German market area from the
[Trading Hub Europe DataExport API](https://api.tradinghub.eu/api/dataexport/manual/en):
imbalance prices, balancing gas, conversion, consumption and the market area
monitor. The crawler stores each report row as JSON and every numeric field as
one value row.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/tradinghub.py` |
| Schema | `tradinghub` |
| Access | none (the API requires a User-Agent; the crawler sends one) |
| Licence | not stated (the metadata refers to the THE transparency data terms) |
| Resolution | gas day |
| Dashboard | `Crawlers/tradinghub.json` |

## Data

By default the crawler loads eleven reports from
`https://api.tradinghub.eu/api/dataexport/xmlexport/<report>`:
`PricesEnergyImbalance`, `PricesEnergyImbalancePreliminary`,
`PricesFlexibilityCharge`, `ExternalBalancingGas`, `InternalBalancingGas`,
`BalancingGasContractedCapacity`, `CommercialConversion`,
`TechnicalConversion`, `AggregatedConsumptionData`,
`AggregateImbalancePositions` and `MarketAreaMonitor`.

| Table | Content | Key |
| --- | --- | --- |
| `report_rows` | One row per XML record: `report_id`, `row_number`, `source_url`, the record as `payload_json`, `fetched_at` | `report_id`, `row_number`, `fetched_at` |
| `report_values` | One row per numeric field: `measure` (field name), `value`, `gas_day`, `status`, `unit`, `dimension` (the non-numeric fields as `name=value; ...`), `record_key` | none |
| `latest_report_values` | View: newest `gas_day` per `report_id`, `measure`, `dimension` | |
| `report_summary` | View: value rows, first and last `gas_day`, last fetch per report | |
| `access_status` | Access model and status of the source | `source_name` |

`gas_day` is a date, taken from the first date field of the record (`GasDay`,
`Date`, `ValidFrom`, ...). `fetched_at` is the UTC time of the run. `unit` is
copied from the report; the crawler does not convert values. Each run also
updates the row of `tradinghub` in `public.metadata`.

## Configuration

```yaml
tradinghub:
  enable: false
  schema_name: tradinghub
  description: Crawls Trading Hub Europe public XML interface reports
  schedule: 40 5 * * *
  lookback_days: 45
```

`lookback_days` (default 45) sets the date window, from today minus
`lookback_days` to today (UTC). `reports` replaces the default report list,
`user_agent` the User-Agent and `request_timeout_seconds` (default 90) the
request timeout.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl tradinghub
```

## Notes

- Each run deletes, per report, all `report_rows` and the `report_values` in
  the date window (and those without `gas_day`), then writes the new rows.
- `PricesEnergyImbalancePreliminary`, `PricesFlexibilityChargeIntraday` and
  `AggregateImbalancePositions` take no date range; the API returns only the
  running gas day. For them a run replaces only the gas days it received, so
  their history grows by one day per run. The preliminary prices have no
  `gas_day` (their dates are separate fields) and always hold the latest
  snapshot only.
- A failing report is logged and the other reports are still loaded; the run
  then ends as failed.
