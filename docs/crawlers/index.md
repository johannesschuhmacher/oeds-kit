# Crawlers

Each crawler loads one source into its own database schema. All crawlers start
disabled; switch them on in [CRAWLER_CONFIG.yml](../configuration.md). Keys and
passwords go into `runtime/crawler/.env`.

Whether and how data may be passed on is decided by the source's terms, not by
OEDS. The licence column shows what the crawler records in `public.metadata`;
"not stated" means the code records no licence and the source terms apply.

| Crawler | Source | Schema | Access | Licence |
| --- | --- | --- | --- | --- |
| [copernicus_cds](copernicus_cds.md) | Copernicus Climate Data Store | `copernicus_cds` | token, dataset terms accepted | not stated |
| [dwd_cdc](dwd_cdc.md) | DWD Climate Data Center | `dwd_cdc` | none | DWD open data terms |
| [eex_eua_auctions](eex_eua_auctions.md) | EEX EU ETS primary auctions (EUA prices) | `eex_eua_auctions` | none | EEX terms, no public republication |
| [eia](eia.md) | U.S. Energy Information Administration | `eia` | API key | not stated |
| [energyforecast](energyforecast.md) | Energy Forecast price predictions | `energyforecast` | token | proprietary |
| [entsoe_api](entsoe_api.md) | ENTSO-E Transparency Platform, Web API | `entsoe_api` | security token | not stated |
| [entsoe_files](entsoe_files.md) | ENTSO-E Transparency Platform, File Library | `entsoe_files` | account | not stated |
| [entsog](entsog.md) | ENTSOG Transparency Platform | `entsog` | none | ENTSOG terms of use |
| [epex_spot](epex_spot.md) | EPEX SPOT market data (SFTP) | `epex_spot` | paid account | not stated |
| [eurostat](eurostat.md) | Eurostat | `eurostat` | none | not stated |
| [gie_agsi_alsi](gie_agsi_alsi.md) | GIE AGSI+ and ALSI | `gie_agsi_alsi` | free API key | not stated |
| [mastr](mastr.md) | Marktstammdatenregister | `mastr` | none | DL-DE/BY-2-0 |
| [netztransparenz](netztransparenz.md) | Netztransparenz.de WebAPI | `netztransparenz` | OAuth2 client | not stated |
| [open_meteo](open_meteo.md) | DWD ICON via Open-Meteo, 1-degree grid | `open_meteo` | none | CC BY 4.0 |
| [powerplantmatching](powerplantmatching.md) | powerplantmatching power plant list | `powerplantmatching` | none | MIT |
| [prisma_capacity](prisma_capacity.md) | PRISMA capacity platform | `prisma_capacity` | paid API package | subscription terms |
| [pypsa_technology_data](pypsa_technology_data.md) | PyPSA technology-data cost assumptions | `pypsa_technology_data` | none | sources' terms (code GPL-3.0) |
| [regelleistung](regelleistung.md) | regelleistung.net | `regelleistung` | none | not stated |
| [renewables_ninja](renewables_ninja.md) | Renewables.ninja | `renewables_ninja` | none | CC BY 4.0 |
| [smard](smard.md) | SMARD (Bundesnetzagentur) | `smard` | none | CC BY 4.0 |
| [tradinghub](tradinghub.md) | Trading Hub Europe | `tradinghub` | none | not stated |
| [tyndp_pecd](tyndp_pecd.md) | TYNDP 2024/2026 Pan-European Climate Database | `tyndp_pecd` | none | CC BY 4.0 |
| [worldbank_commodities](worldbank_commodities.md) | World Bank Pink Sheet commodity prices | `worldbank_commodities` | none | CC BY 4.0 |

`oeds-crawl --list` also shows the crawlers of the OEDS core
([oeds-core](https://github.com/johannesschuhmacher/oeds-core)). They run the
same way, but are not part of the configuration template and not documented
here; a crawler of this list replaces a core crawler of the same name.

```{toctree}
:hidden:
:glob:

*
```
