# Grafana dashboards

Two starter dashboards are provisioned by default: SMARD and Weather. They
were exported read-only from <https://oeds.iip.kit.edu> and use the local
`OPENDATA` datasource. No changes are made to the production server.
The starter SMARD view shows generation/load and day-ahead prices in English.
The original cross-source comparison is preserved as an optional dashboard,
since it needs the separate `entsoe.query_generation` table.

Load sample data before opening them. For the fixed historical SMARD sample,
select June 3-10, 2024 in Grafana's time picker. For Weather, select Germany
and Berlin, with the current day as the time range.
The starter map explicitly uses OpenStreetMap, avoiding a separate CARTO API
key. It requires browser access to the tile service; for large deployments,
configure a suitable tile provider and retain its attribution.

## Optional dashboards

All other dashboards are preserved in `optional-dashboards/`, outside the
automatically provisioned directory. This includes ENTSO-E, forecasts, gapfill
quality, source-specific dashboards and heatwave/event research views. Internal
and external variants are retained, but no longer clutter a fresh installation.

To enable a dashboard, first enable its crawler and load the required tables.
Then import its JSON in Grafana using **Dashboards > New > Import**, selecting
the `OPENDATA` datasource. Imported dashboards are stored in Grafana's persistent
volume. They survive a normal update, but not a destructive reset.

Alternatively, copy selected JSON files into a subdirectory of `dashboards/`
in your deployment checkout before installing. Check for duplicate UIDs when
enabling multiple variants. The specialist dashboards require their documented
source datasets; a small SMARD/Weather sample cannot validate all their panels.

## Check or refresh

Run `python3 tools/check_dashboards.py` from the deployment repository on the VM
after loading sample data and starting all services. It checks HTTP endpoints
and executes each starter panel's SQL through Grafana, using the readonly role.
It fails on SQL errors or a dashboard with no returned sample rows.

`python3 tools/sync_grafana_dashboards.py` refreshes the two source exports.
Review and retest the diff before committing it. Exports do not contain
datasource passwords. Credentials belong in environment files, never JSON.
