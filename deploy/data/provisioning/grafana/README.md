# Grafana dashboards

Grafana provisions every JSON file below `dashboards/`. Each subdirectory becomes
a Grafana folder:

- `Crawlers/` has one dashboard per crawler, named after the crawler section in
  `CRAWLER_CONFIG.yml` (for example `Crawlers/epex_spot.json`). A dashboard shows
  data once its crawler has run; before that its panels report missing tables.
- `Analyses/` has dashboards that combine sources: day-ahead price forecast,
  energy weather, and the ENTSO-E cross-border, country, stress, forecast
  accuracy and negative price views, and ENTSO-E power plants and
  availability. Its plant maps need the `power_system_data` crawler, its
  availability map the `entsoe_fms` crawler, whose post-run script
  `oeds-post refresh entsoe-availability-map` fills it.

The SMARD and Weather dashboards were exported read-only from
<https://oeds.iip.kit.edu>; `python3 tools/sync_grafana_dashboards.py` refreshes
them. Review and retest the diff before committing it. Exports do not contain
datasource passwords. Credentials belong in environment files, never JSON.

Maps use OpenStreetMap tiles and need browser access to the tile service; for
large deployments, configure a suitable tile provider and keep its attribution.

## Not provisioned

`optional-dashboards/` keeps dashboards that need data a standard installation
does not load: the public (external) variants of the ENTSO-E analyses, the 2026
heatwave and negative-price event studies, hydro and transfer-capacity views,
GloHydroRes, gapfill quality and PRISMA (needs an API subscription). To use one, copy it into a
subdirectory of `dashboards/` and check for duplicate UIDs.

## Check

`python3 tools/check_dashboards.py` (part of the installation test) checks the
HTTP endpoints and requires the SMARD and Weather panels to return data.

`python3 tools/check_dashboards.py --all` runs every SQL query of every
provisioned dashboard through Grafana, with each variable at its default value.
It fails on SQL errors and lists panels that return no rows in the default
time range.
