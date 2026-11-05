# EPEX SPOT

German intraday market data from the market-data SFTP service of EPEX SPOT
(`sftp://sftp.marketdata.epexspot.com/germany`): continuous trading statistics, indices and transactions, and the
pan-European intraday auctions IDA1, IDA2 and IDA3.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/epex_spot.py` |
| Schema | `epex_spot` |
| Access | EPEX SPOT SFTP account (`EPEX_SFTP_USERNAME`, `EPEX_SFTP_PASSWORD`) |
| Licence | not stated (metadata: "EPEX SPOT market data account") |
| Resolution | per product; IDA 15 minutes |
| Dashboard | `Crawlers/epex_spot.json` |

## Data

The crawler reads CSV files from `Intraday Continuous/EOD/Results`,
`Intraday Continuous/Indices/Intraday indices`, the ZIP archives in
`Intraday Continuous/EOD/Transactions` and the `Current/Prices_Volumes`
folders of the three IDA auctions.

| Table | Content | Key |
| --- | --- | --- |
| `continuous_statistics` | Low, high, last and volume-weighted average price, buy and sell volume per delivery period, `market_area` `DE` | `market_area`, `delivery_start_utc`, `delivery_end_utc` |
| `continuous_indices` | `index_price` and `index_volume` per `index_name` and `time_resolution`, `market_area` `DE` | `market_area`, `index_name`, `time_resolution`, `delivery_start_utc`, `delivery_end_utc` |
| `intraday_auction_prices_volumes` | One row per `auction_name` (IDA1–IDA3), `metric` (`price` in EUR, `volume` in MWH) and quarter hour, `market_area` `DE-LU` | `auction_name`, `market_area`, `metric`, `delivery_start_utc`, `delivery_end_utc` |
| `continuous_trades` | Single trades: price, volume, product, execution time, delivery area, trade phase | `trade_id`, `side`, `order_id` |
| `imported_files` | Remote files already written, with row count | `remote_path`, `file_size`, `file_mtime` |

The columns ending in `_utc` are `timestamp with time zone`. Currency and volume
unit of the continuous data are stored as given in the files (`currency`,
`volume_unit`). For the auctions, `delivery_day` is the delivery date in
Europe/Berlin and `time_label` the original product column (`Hour 3B Q2`).
Every row keeps `source_file`, `publication_time_utc` (from the file header)
and `download_time_utc`. Each run updates the row of `epex_spot` in
`public.metadata`.

## Configuration

```yaml
epex_spot:
  enable: false
  schema_name: epex_spot
  database_uri: postgresql://opendata:opendata@127.0.0.1:6432/opendata?options=--search_path=
  description: Crawls EPEX SPOT Germany intraday market data via SFTP
  schedule: 20 * * * *
  start_date: '1970-01-01'
  update_interval_days: 14
  database_batch_size: 100000
  include_continuous_statistics: true
  include_continuous_indices: true
  include_intraday_auctions: true
  include_continuous_trades: true
```

`start_date` is read as Europe/Berlin time when it has no offset;
`continuous_trades_start_date` and `intraday_auction_start_date` override it
for those datasets. `target_datasets` (a list of `continuous_statistics`,
`continuous_indices`, `intraday_auctions`, `continuous_trades`) replaces the
`include_*` switches. `database_batch_size` is the number of trade rows written
at a time. `sftp_host`, `sftp_port`, `sftp_username` and `sftp_password` can be
set in the config; the environment variables `EPEX_SFTP_HOST`,
`EPEX_SFTP_PORT`, `EPEX_SFTP_USERNAME` and `EPEX_SFTP_PASSWORD` take
precedence. `username_env` and `password_env` rename the two credential
variables.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl epex_spot
```

## Notes

- Each dataset starts at `update_interval_days` before its newest stored
  delivery start, or at `start_date` when the table is empty. Files whose day
  or year in the name ends before that start are not opened, and rows with an
  earlier delivery start are dropped.
- Files listed in `imported_files` with the same size and modification time are
  skipped, so unchanged trade archives are not imported again.
- Trade archives are read in chunks of `database_batch_size` rows. With
  `start_date: '1970-01-01'` the first run loads every file on the server and
  takes much longer than later runs.
- The SFTP session is reopened and a file read retried up to three times when
  the server drops the connection.
