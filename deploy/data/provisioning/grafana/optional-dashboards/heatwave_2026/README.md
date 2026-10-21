# Heatwave 2026 Interactive Grafana Dashboards

These dashboards query the OEDS PostgreSQL datasource directly. They do not embed PNG images.

- Required schema: `heatwave_2026`
- Load/update data with: `python scripts/load_heatwave_2026_to_postgres.py`
- Generate dashboards with: `python scripts/generate_heatwave_grafana_dashboards.py`
- Grafana datasource UID: `P6EAA63344BCC9F38`
