# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATASOURCE = {"type": "grafana-postgresql-datasource", "uid": "P6EAA63344BCC9F38"}
DASHBOARD_DIR = Path("data/provisioning/grafana/dashboards")
TARGET_DIRS = {
    "Copernicus_CDS.json": "copernicus_cds",
    "DWD_Climate_Data_Center.json": "dwd_cdc",
    "EIA_Open_Data.json": "eia",
    "GIE_AGSI_ALSI.json": "gie_agsi_alsi",
    "Netztransparenz_WebAPI.json": "netztransparenz",
    "Open_Meteo.json": "open_meteo",
    "OpenStreetMap_Power.json": "osm_power",
    "PRISMA_Capacity_API.json": "prisma_capacity",
    "Regelleistung_Datacenter.json": "regelleistung",
    "Trading_Hub_Europe.json": "tradinghub",
}


def target(raw_sql: str, ref_id: str = "A", fmt: str = "table") -> dict[str, Any]:
    return {
        "refId": ref_id,
        "editorMode": "code",
        "format": fmt,
        "rawQuery": True,
        "rawSql": raw_sql,
    }


def stat_panel(panel_id: int, title: str, sql: str, x: int, y: int, w: int = 6, h: int = 4, unit: str = "short") -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, fmt="time_series")],
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "auto",
            "wideLayout": True,
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": [],
        },
    }


def table_panel(panel_id: int, title: str, sql: str, x: int, y: int, w: int = 24, h: int = 8) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "table",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, fmt="table")],
        "options": {"cellHeight": "sm", "footer": {"show": False, "reducer": ["sum"]}, "showHeader": True},
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def timeseries_panel(panel_id: int, title: str, sql: str, x: int, y: int, w: int = 24, h: int = 9, unit: str = "short") -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, fmt="time_series")],
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisPlacement": "auto",
                    "drawStyle": "line",
                    "fillOpacity": 12,
                    "gradientMode": "none",
                    "lineInterpolation": "linear",
                    "lineWidth": 2,
                    "showPoints": "never",
                    "spanNulls": True,
                    "stacking": {"mode": "none", "group": "A"},
                },
            },
            "overrides": [],
        },
    }


def geomap_panel(panel_id: int, title: str, sql: str, x: int, y: int, w: int = 12, h: int = 10) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "geomap",
        "title": title,
        "datasource": DATASOURCE,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, fmt="table")],
        "fieldConfig": {"defaults": {"color": {"mode": "continuous-BlYlRd"}}, "overrides": []},
        "options": {
            "basemap": {"type": "default", "name": "Layer 0"},
            "controls": {"mouseWheelZoom": True, "showAttribution": True, "showMeasure": False, "showScale": False, "showZoom": True},
            "layers": [
                {
                    "type": "markers",
                    "name": "Locations",
                    "filterData": {"id": "byRefId", "options": "A"},
                    "location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"},
                    "tooltip": True,
                    "config": {
                        "showLegend": True,
                        "style": {
                            "color": {"field": "value"},
                            "opacity": 0.7,
                            "size": {"fixed": 7, "min": 4, "max": 14},
                            "symbol": {"fixed": "img/icons/marker/circle.svg", "mode": "fixed"},
                        },
                    },
                }
            ],
            "tooltip": {"mode": "details"},
            "view": {"id": "europe", "lat": 51, "lon": 10, "zoom": 4},
        },
    }


def access_sql(schema: str, source_name: str) -> str:
    return (
        "SELECT status, access_model, credentials_required, configured_credentials, "
        f"message, docs_url, checked_at FROM {schema}.access_status "
        f"WHERE source_name = '{source_name}' ORDER BY checked_at DESC LIMIT 1"
    )


def dashboard(title: str, uid: str, tags: list[str], panels: list[dict[str, Any]], time_from: str = "now-30d", time_to: str = "now") -> dict[str, Any]:
    return {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": False,
        "panels": panels,
        "refresh": "1h",
        "schemaVersion": 39,
        "style": "dark",
        "tags": tags,
        "templating": {"list": []},
        "time": {"from": time_from, "to": time_to},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


DASHBOARDS = {
    "Netztransparenz_WebAPI.json": dashboard(
        "Netztransparenz WebAPI",
        "netztransparenz-webapi",
        ["energy", "netztransparenz"],
        [
            table_panel(1, "Access Status", access_sql("netztransparenz", "Netztransparenz WebAPI"), 0, 0, 18, 4),
            stat_panel(2, "Normalized Values", "SELECT now() AS time, count(*)::double precision AS value FROM netztransparenz.normalized_values", 18, 0),
            timeseries_panel(
                3,
                "Recent Values",
                "SELECT timestamp_from AS time, endpoint_id || ' / ' || area AS metric, value FROM netztransparenz.normalized_values WHERE timestamp_from IS NOT NULL AND $__timeFilter(timestamp_from) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "Latest Values", "SELECT endpoint_id, label, area, direction, unit, value, timestamp_from, status FROM netztransparenz.latest_values ORDER BY endpoint_id, area LIMIT 200", 0, 13),
        ],
    ),
    "Regelleistung_Datacenter.json": dashboard(
        "regelleistung.net Datacenter",
        "regelleistung-datacenter",
        ["energy", "balancing"],
        [
            table_panel(1, "Access Status", access_sql("regelleistung", "regelleistung.net Datacenter"), 0, 0, 18, 4),
            stat_panel(2, "Tender Files", "SELECT now() AS time, count(*)::double precision AS value FROM regelleistung.tender_files", 18, 0),
            timeseries_panel(
                3,
                "Numeric Workbook Values",
                "SELECT delivery_date AS time, product_type || ' / ' || market || ' / ' || measure AS metric, value FROM regelleistung.numeric_values WHERE delivery_date IS NOT NULL AND $__timeFilter(delivery_date) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "File Summary", "SELECT * FROM regelleistung.file_summary ORDER BY product_type, market, file_type", 0, 13),
        ],
    ),
    "GIE_AGSI_ALSI.json": dashboard(
        "GIE AGSI/ALSI",
        "gie-agsi-alsi",
        ["energy", "gas", "lng"],
        [
            table_panel(1, "Access Status", access_sql("gie_agsi_alsi", "GIE AGSI/ALSI"), 0, 0, 18, 4),
            stat_panel(2, "Inventory Rows", "SELECT now() AS time, count(*)::double precision AS value FROM gie_agsi_alsi.daily_inventory", 18, 0),
            timeseries_panel(
                3,
                "Storage/LNG Fill Level",
                "SELECT gas_day_start::timestamp AS time, platform || ' / ' || scope || ' / ' || coalesce(name, code) AS metric, full_pct AS value FROM gie_agsi_alsi.daily_inventory WHERE full_pct IS NOT NULL AND $__timeFilter(gas_day_start::timestamp) ORDER BY 1, 2",
                0,
                4,
                unit="percent",
            ),
            table_panel(4, "Latest Inventory", "SELECT platform, scope, name, code, gas_day_start, gas_in_storage, working_gas_volume, full_pct, injection, withdrawal, status FROM gie_agsi_alsi.latest_inventory ORDER BY platform, scope, name LIMIT 200", 0, 13),
        ],
    ),
    "Trading_Hub_Europe.json": dashboard(
        "Trading Hub Europe",
        "trading-hub-europe",
        ["energy", "gas"],
        [
            table_panel(1, "Access Status", access_sql("tradinghub", "Trading Hub Europe XML Interface"), 0, 0, 18, 4),
            stat_panel(2, "Report Values", "SELECT now() AS time, count(*)::double precision AS value FROM tradinghub.report_values", 18, 0),
            timeseries_panel(
                3,
                "Report Values",
                "SELECT gas_day::timestamp AS time, report_id || ' / ' || measure AS metric, value FROM tradinghub.report_values WHERE gas_day IS NOT NULL AND $__timeFilter(gas_day::timestamp) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "Report Summary", "SELECT * FROM tradinghub.report_summary ORDER BY report_id", 0, 13),
        ],
    ),
    "PRISMA_Capacity_API.json": dashboard(
        "PRISMA Capacity API",
        "prisma-capacity-api",
        ["energy", "gas", "capacity"],
        [
            table_panel(1, "Access Status", access_sql("prisma_capacity", "PRISMA Capacity Platform API"), 0, 0, 18, 4),
            stat_panel(2, "Imported Rows", "SELECT now() AS time, count(*)::double precision AS value FROM prisma_capacity.raw_resources", 18, 0),
            table_panel(3, "Resource Summary", "SELECT * FROM prisma_capacity.resource_summary ORDER BY resource_id", 0, 4, 12, 9),
            table_panel(4, "Latest Raw Resources", "SELECT resource_id, source_url, fetched_at, row_number, payload_json FROM prisma_capacity.raw_resources ORDER BY fetched_at DESC, resource_id LIMIT 200", 12, 4, 12, 9),
        ],
    ),
    "OpenStreetMap_Power.json": dashboard(
        "OpenStreetMap Power",
        "openstreetmap-power",
        ["energy", "osm", "infrastructure"],
        [
            table_panel(1, "Access Status", access_sql("osm_power", "OpenStreetMap / Overpass power data"), 0, 0, 18, 4),
            stat_panel(2, "Power Features", "SELECT now() AS time, count(*)::double precision AS value FROM osm_power.power_features", 18, 0),
            geomap_panel(
                3,
                "Power Feature Map",
                "SELECT 0 AS time, latitude, longitude, coalesce(name, osm_type || '/' || osm_id::text) AS name, power, operator, 1::double precision AS value FROM osm_power.power_features WHERE latitude IS NOT NULL AND longitude IS NOT NULL LIMIT 5000",
                0,
                4,
                12,
                10,
            ),
            table_panel(4, "Feature Summary", "SELECT * FROM osm_power.power_feature_summary ORDER BY features DESC", 12, 4, 12, 10),
        ],
    ),
    "DWD_Climate_Data_Center.json": dashboard(
        "DWD Climate Data Center",
        "dwd-climate-data-center",
        ["weather", "climate", "dwd"],
        [
            table_panel(1, "Access Status", access_sql("dwd_cdc", "DWD Climate Data Center"), 0, 0, 18, 4),
            stat_panel(2, "Observations", "SELECT now() AS time, count(*)::double precision AS value FROM dwd_cdc.regional_monthly", 18, 0),
            timeseries_panel(
                3,
                "Germany Monthly Climate",
                "SELECT period_start AS time, variable AS metric, value FROM dwd_cdc.germany_monthly WHERE $__timeFilter(period_start) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "Regional Summary", "SELECT * FROM dwd_cdc.regional_summary ORDER BY variable, region", 0, 13),
        ],
        time_from="now-20y",
    ),
    "Copernicus_CDS.json": dashboard(
        "Copernicus Climate Data Store",
        "copernicus-cds",
        ["weather", "climate", "copernicus"],
        [
            table_panel(1, "Access Status", access_sql("copernicus_cds", "Copernicus Climate Data Store"), 0, 0, 18, 4),
            stat_panel(2, "Downloaded Files", "SELECT now() AS time, count(*)::double precision AS value FROM copernicus_cds.downloaded_files", 18, 0),
            table_panel(3, "Variable Statistics", "SELECT * FROM copernicus_cds.variable_statistics ORDER BY fetched_at DESC, variable", 0, 4, 12, 9),
            table_panel(4, "Requests", "SELECT request_id, dataset, status, target_path, requested_at, completed_at, error FROM copernicus_cds.requests ORDER BY requested_at DESC LIMIT 100", 12, 4, 12, 9),
        ],
    ),
    "Open_Meteo.json": dashboard(
        "Open-Meteo Forecasts",
        "open-meteo-forecasts",
        ["weather", "forecast", "open-meteo"],
        [
            table_panel(1, "Access Status", access_sql("open_meteo", "Open-Meteo"), 0, 0, 18, 4),
            stat_panel(2, "Forecast Values", "SELECT now() AS time, count(*)::double precision AS value FROM open_meteo.hourly_forecast", 18, 0),
            timeseries_panel(
                3,
                "Hourly Forecast Values",
                "SELECT valid_time AS time, location_id || ' / ' || variable AS metric, value FROM open_meteo.hourly_forecast WHERE $__timeFilter(valid_time) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "Location Summary", "SELECT * FROM open_meteo.location_summary ORDER BY location_id, variable", 0, 13),
        ],
        time_from="now-24h",
        time_to="now+5d",
    ),
    "EIA_Open_Data.json": dashboard(
        "EIA Open Data",
        "eia-open-data",
        ["energy", "eia"],
        [
            table_panel(1, "Access Status", access_sql("eia", "U.S. EIA Open Data API"), 0, 0, 18, 4),
            stat_panel(2, "Numeric Values", "SELECT now() AS time, count(*)::double precision AS value FROM eia.numeric_values", 18, 0),
            timeseries_panel(
                3,
                "Numeric API Values",
                "SELECT period AS time, request_id || ' / ' || measure AS metric, value FROM eia.numeric_values WHERE period IS NOT NULL AND $__timeFilter(period) ORDER BY 1, 2",
                0,
                4,
            ),
            table_panel(4, "Latest Values", "SELECT request_id, period, dimension, measure, value, unit, fetched_at FROM eia.latest_values ORDER BY request_id, measure, dimension LIMIT 200", 0, 13),
        ],
    ),
}


def main() -> None:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, content in DASHBOARDS.items():
        target_dir = DASHBOARD_DIR / TARGET_DIRS[file_name]
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / file_name
        path.write_text(json.dumps(content, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
