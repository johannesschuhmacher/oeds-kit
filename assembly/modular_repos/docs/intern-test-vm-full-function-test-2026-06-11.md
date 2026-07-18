# Intern-Test VM Full Function Smoke 2026-06-11

Ziel: Die neue modulare OEDS-Struktur auf `iip-vm-oeds-intern-test.iip.kit.edu`
mit echter Runtime-`.env`, Docker-Stack, Datenbank, Admin UI, Scheduler,
Crawlern, Post-Scripts und ENTSO-E-Backfill pruefen.

## Rahmen

- VM: `iip-vm-oeds-intern-test.iip.kit.edu`
- Benutzer: `oeds`
- Runtime: `/open_energy_data_server/runtime`
- Repo: `/open_energy_data_server/repo`
- Ergebnisdatei auf der VM: `/home/oeds/oeds_full_smoke_results.json`
- Logdatei auf der VM: `/home/oeds/oeds_full_smoke.log`
- Runtime-Konfiguration wurde vor den Tests gesichert und nach den Tests wiederhergestellt.
- Die lokale `crawler/.env` wurde nach `/open_energy_data_server/runtime/crawler/.env` kopiert.
- Secret-Werte wurden im Testlog nicht ausgegeben.

## Ablauf

1. Admin/Scheduler-Container mit echter Runtime-`.env` neu gestartet.
2. Admin-HTTP-Smoke ausgefuehrt:
   - `/admin/healthz`
   - `/admin`
   - `/admin/editor`
   - `/admin/gapfill`
   - `/admin/crawlers/entsoe_api`
3. Importcheck fuer alle Crawler-Module im Container ausgefuehrt.
4. Gapfill-Selftests ueber die Admin UI ausgefuehrt.
5. Crawler-Kurzlaeufe ueber Admin Actions mit engen Fenstern ausgefuehrt.
6. ENTSO-E FMS Backfill und Gapfill-Backfill ausgefuehrt.
7. Scheduler-Smoke mit temporaerem `weather_forecast`-Minutentakt ausgefuehrt.
8. Originale Runtime-Konfiguration wiederhergestellt.

## Gefundene Fehler Und Fixes

### `refresh_entsoe_availability_map.py` konnte `crawler_core` nicht importieren

Fehlerbild:

```text
ModuleNotFoundError: No module named 'crawler_core'
```

Ursache:

- Post-Scripts werden als `python scripts/...py` ausgefuehrt.
- Dadurch liegt `/app/scripts` in `sys.path`, aber nicht zwingend `/app`.

Fix:

- `scripts/refresh_entsoe_availability_map.py` setzt den Repo-Root vor dem Import in `sys.path`.
- `scripts/lib/gapfill.py` wurde analog gehaertet.
- `docker/Dockerfile.crawler` setzt `PYTHONPATH=/app`.
- Die gleiche Script-Aenderung wurde in `modular_repos/modules/oeds-post-scripts/...` nachgezogen.

### Availability-Map-Refresh scheiterte bei gezieltem `EnergyPrices`-Run

Fehlerbild:

```text
relation "entsoe_fms.UnavailabilityOfProductionAndGenerationUnits" does not exist
```

Ursache:

- `scripts/lib/entsoe_availability_map.sql` benoetigt die Availability-Quelltabellen:
  - `entsoe_fms.powersystemdata`
  - `entsoe_fms."UnavailabilityOfProductionAndGenerationUnits"`
  - `entsoe_fms."InstalledGenerationCapacityPerProductionUnit"`
- Ein gezielter `EnergyPrices`-Run erzeugt diese Tabellen nicht.

Fix:

- `refresh_entsoe_availability_map.py` prueft die benoetigten Quelltabellen vor dem SQL-Refresh.
- Wenn Tabellen fehlen, wird der Availability-Refresh mit Warnung uebersprungen und das Post-Script beendet erfolgreich.
- Retest `entsoe_fms:entsoe_targeted` war danach erfolgreich.

## Bestandene Tests

| Bereich | Ergebnis |
| --- | --- |
| Admin UI / Health | bestanden |
| Importcheck aller Crawler-Module | bestanden, 0 Importfehler |
| Gapfill-Selftests | bestanden |
| Scheduler-Minuten-Smoke | bestanden |
| Runtime-Konfig Restore | bestanden |

## Crawler-Ergebnisse

| Crawler / Action | Ergebnis | Nachweis |
| --- | --- | --- |
| `weather_forecast:weather_window` | bestanden | `weather.hourly_forecast=2162`, `weather.locations=15` |
| `open_meteo:run_now` | bestanden | `open_meteo.hourly_forecast=24`, `open_meteo.locations=1` |
| `power_system_data:run_now` | bestanden | `power_system_data.powersystemdata=165064`, `power_system_data.eic_geo_location=3016` |
| `eurostat_crawler:eurostat_range` | bestanden | `eurostat.eurostat=2226` |
| `dwd_cdc:run_now` | bestanden | `dwd_cdc.regional_monthly=2482` |
| `osm_power:run_now` | bestanden | `osm_power.power_features=100` |
| `tradinghub:run_now` | bestanden | `tradinghub.report_rows=9`, `tradinghub.report_values=29` |
| `regelleistung:run_now` | bestanden | Retest mit 35 Tagen: `tender_files=6`, `file_rows=2232`, `numeric_values=2232` |
| `gie_agsi_alsi:run_now` | bestanden | `gie_agsi_alsi.daily_inventory=1` |
| `eia:run_now` | bestanden | `eia.api_rows=100`, `eia.numeric_values=100` |
| `netztransparenz:run_now` | bestanden | `netztransparenz.endpoint_runs=1`, `netztransparenz.normalized_values=582` |
| `prisma_capacity:run_now` | bestanden | Erwarteter No-Resource-Lauf: `prisma_capacity.raw_resources=0` |
| `energy_forecast_crawler:run_now` | bestanden | `energy_forecast.predictions_48h=1` |
| `entsoe_api:run_now` | bestanden | `entsoe_api.day_ahead_prices=577` |
| `entsoe_api:price_forecast` | bestanden | Price-Forecast Self-Test erfolgreich |
| `entsoe_fms:entsoe_targeted` | bestanden nach Fix | `EnergyPrices`-Paket 2026-06 verarbeitet, 53135 Upserts |
| `entsoe_fms:entsoe_backfill` | bestanden | Historischer Backfill `EnergyPrices_12.1.D_r3` fuer `2024_06` |
| `entsoe_fms:gapfill_backfill` | bestanden | `entsoe_fms_gapfilled.EnergyPrices=53735` |
| `epex_spot:run_now` | bestanden | `epex_spot.intraday_auction_prices_volumes=960` |
| `entsog:run_now` | bestanden | `entsog.operators=100`, `entsog.physical_flow=24240` |
| `copernicus_cds:run_now` | bestanden | `copernicus_cds.requests=1`, `downloaded_files=1` |
| `smard:run_now` | bestanden | Nachtraeglicher Lauf: `smard.smard=8064`, `smard.prices=672`, `smard.smard_gapfilled=8064` |

## Nicht Als Live-Vollimport Gestartet

Diese Crawler wurden importiert, aber nicht als echter Vollimport gestartet:

| Crawler | Grund |
| --- | --- |
| `mastr` | Kein kleines Testfenster vorhanden; Vollimport zieht den kompletten MaStR-Export. |
| `ninja` | Kein kleines Testfenster vorhanden; Vollimport zieht komplette Renewables.ninja-ZIP-Archive. |

Empfehlung: Fuer beide Crawler einen expliziten Smoke-/Limit-Modus einfuehren,
z. B. `max_files`, `max_rows`, `target_datafiles` oder eine kleine Fixture-URL.
Erst danach kann ein wiederholbarer CI-/VM-Smoke alle Crawler ohne grosse
Netz- und Speicherlast abdecken.

## Fazit

Die modulare Runtime funktioniert auf der Intern-Test-VM mit echter `.env`,
voller Docker-/DB-Integration, Admin UI, Scheduler, Post-Scripts,
ENTSO-E-Backfill und den neuen credential-basierten Crawlern.

Offen fuer einen wirklich vollstaendig automatisierbaren Release-Smoke:

- bounded Smoke-Modus fuer `mastr`
- bounded Smoke-Modus fuer `ninja`
- optional: den VM-Testlaeufer als versioniertes Tool ins Deployment-Repo uebernehmen
