# EEX EU ETS auctions

Results of the EU ETS primary market auctions at EEX
([EU ETS auctions](https://www.eex.com/en/market-data/environmentals/eu-ets-auctions)):
clearing price of EU allowances (EUA) in EUR/tCO2, auctioned volume, bids and
bidders per auction, from 2020.

| | |
| --- | --- |
| Module | `packages/crawler-pack/src/crawler/eex_eua_auctions.py` |
| Schema | `eex_eua_auctions` |
| Access | none |
| Licence | EEX terms of use: no systematic republication or dissemination of substantial parts without EEX permission |
| Resolution | one row per auction (most working days) |
| Dashboard | `Crawlers/eex_eua_auctions.json` |

EEX allows the use of its market data, but republishing a substantial part,
for example on a public dashboard, needs its permission
(datasource@eex-group.com). Run this crawler only on servers whose Grafana is
not public.

## Data

EEX publishes one report per year
(`emission-spot-primary-market-auction-report-<year>-data.xlsx` on
`public.eex-group.com`, from 2020). A run reads all years from `start_year`
(default 2020) to the current year.

| Table | Content | Key |
| --- | --- | --- |
| `auctions` | `auction_price`, `minimum_bid`, `maximum_bid`, `mean_bid` and `median_bid` (EUR/tCO2), `auction_volume` and `total_bid_volume` (tCO2), numbers of bids and bidders, `cover_ratio`, `total_revenue` (EUR), `zone` (`EU`, `DE`, `PL`, `XI`), `status` and `market` (sheet name) | `auction_date`, `auction_name`, `contract` |
| `access_status` | One row on the access model and the terms of the source | `source_name` |

`contract` is `T3PA` for EU allowances and `EAA3` for aviation allowances
(auctioned until 2024). `published_at` is the time in the report (Europe/Berlin,
without time zone). The revenue per member state in the report is not loaded.

The view `eua_daily_price` holds the volume-weighted clearing price of the
successful EUA auctions per day (`price_eur_per_t`, `volume_t`, `auctions`).
Each run updates the row of `eex_eua_auctions` in `public.metadata`.

## Configuration

```yaml
eex_eua_auctions:
  enable: false
  schema_name: eex_eua_auctions
  description: Loads the EEX EU ETS primary auction results (EUA clearing prices)
  schedule: 0 12 * * *
```

`start_year` (default 2020, the first yearly report available) sets the first
year. `request_timeout_seconds` (default 60) and `user_agent` set the HTTP
requests.

## Run by hand

```bash
docker exec oeds-scheduler oeds-crawl eex_eua_auctions
```

## Notes

- Each run replaces the whole table; the reports are small (about 90 kB per
  year).
- Until the first auction of a year, its report does not exist; the run then
  loads the previous years only.
- Auction prices are close to, but not the same as, the secondary market
  (ICE EUA futures) price.
