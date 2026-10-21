"""Generate the Grafana dashboard JSON for GloHydroRes."""

from __future__ import annotations

import json
from pathlib import Path


OUTFILE = Path("data/provisioning/grafana/dashboards/shared/GloHydroRes_Hydro_Plants_Reservoirs.json")
DATASOURCE_UID = "P6EAA63344BCC9F38"


def datasource() -> dict:
    return {"type": "grafana-postgresql-datasource", "uid": DATASOURCE_UID}


def stat_panel(panel_id: int, title: str, raw_sql: str, grid_pos: dict, unit: str, decimals: int = 0) -> dict:
    return {
        "datasource": datasource(),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "continuous-BlYlRd"},
                "decimals": decimals,
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": unit,
            },
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
        "pluginVersion": "11.3.1",
        "targets": [
            {
                "editorMode": "code",
                "format": "time_series",
                "rawQuery": True,
                "rawSql": raw_sql,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "stat",
    }


def bar_chart_panel(panel_id: int, title: str, raw_sql: str, grid_pos: dict, x_field: str, color_by_field: str = "") -> dict:
    return {
        "datasource": datasource(),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "barRadius": 0,
            "barWidth": 0.86,
            "colorByField": color_by_field,
            "fullHighlight": False,
            "groupWidth": 0.7,
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "orientation": "auto",
            "showValue": "never",
            "stacking": "none",
            "tooltip": {"hideZeros": False, "mode": "single", "sort": "none"},
            "xField": x_field,
            "xTickLabelRotation": 0,
            "xTickLabelSpacing": 0,
        },
        "pluginVersion": "11.3.1",
        "targets": [
            {
                "editorMode": "code",
                "format": "table",
                "rawQuery": True,
                "rawSql": raw_sql,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "barchart",
    }


def table_panel(panel_id: int, title: str, raw_sql: str, grid_pos: dict) -> dict:
    return {
        "datasource": datasource(),
        "fieldConfig": {"defaults": {"mappings": [], "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}}, "overrides": []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "cellHeight": "sm",
            "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
            "showHeader": True,
            "sortBy": [{"desc": True, "displayName": "capacity_mw"}],
        },
        "pluginVersion": "11.3.1",
        "targets": [
            {
                "editorMode": "code",
                "format": "table",
                "rawQuery": True,
                "rawSql": raw_sql,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "table",
    }


def geomap_panel(panel_id: int, title: str, raw_sql: str, grid_pos: dict) -> dict:
    return {
        "datasource": datasource(),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "continuous-BlPu"},
                "decimals": 1,
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": "megwatt",
            },
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "basemap": {"config": {}, "name": "Layer 0", "type": "default"},
            "controls": {
                "mouseWheelZoom": True,
                "showAttribution": True,
                "showDebug": False,
                "showMeasure": False,
                "showScale": False,
                "showZoom": True,
            },
            "layers": [
                {
                    "config": {
                        "showLegend": True,
                        "style": {
                            "color": {"field": "capacity_mw"},
                            "opacity": 0.8,
                            "rotation": {"fixed": 0, "max": 360, "min": -360, "mode": "mod"},
                            "size": {"field": "capacity_mw", "fixed": 6, "max": 18, "min": 4},
                            "symbol": {"field": "", "fixed": "", "mode": "fixed"},
                            "symbolAlign": {"horizontal": "center", "vertical": "center"},
                            "textConfig": {
                                "fontSize": 12,
                                "offsetX": 0,
                                "offsetY": 0,
                                "textAlign": "center",
                                "textBaseline": "middle",
                            },
                        },
                    },
                    "location": {"latitude": "lat", "longitude": "lon", "mode": "coords"},
                    "name": "Layer 1",
                    "tooltip": True,
                    "type": "markers",
                }
            ],
            "tooltip": {"mode": "details"},
            "view": {"allLayers": True, "lat": 18, "lon": 5, "zoom": 1},
        },
        "pluginVersion": "11.3.1",
        "targets": [
            {
                "editorMode": "code",
                "format": "table",
                "rawQuery": True,
                "rawSql": raw_sql,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "geomap",
    }


def main() -> None:
    filter_sql = "country IN (${Country:sqlstring}) AND plant_type IN (${Plant_Type:sqlstring})"

    dashboard = {
        "__inputs": [],
        "__requires": [
            {"type": "datasource", "id": "grafana-postgresql-datasource", "name": "OPENDATA", "version": "1.0.0"},
            {"type": "panel", "id": "stat", "name": "Stat", "version": "11.3.1"},
            {"type": "panel", "id": "table", "name": "Table", "version": "11.3.1"},
            {"type": "panel", "id": "geomap", "name": "Geomap", "version": "11.3.1"},
            {"type": "panel", "id": "barchart", "name": "Bar chart", "version": "11.3.1"},
        ],
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
        "description": "Global hydro plants and linked reservoirs from GloHydroRes_vs1. Source CSV imported into schema glohydrores.",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "liveNow": False,
        "panels": [
            stat_panel(
                1,
                "Hydro Plants",
                f"SELECT now() AS \"time\", COUNT(*) AS value FROM glohydrores.plants_dashboard WHERE {filter_sql}",
                {"h": 4, "w": 6, "x": 0, "y": 0},
                "none",
            ),
            stat_panel(
                2,
                "Installed Capacity",
                f"SELECT now() AS \"time\", SUM(capacity_mw) AS value FROM glohydrores.plants_dashboard WHERE {filter_sql}",
                {"h": 4, "w": 6, "x": 6, "y": 0},
                "megwatt",
                1,
            ),
            stat_panel(
                3,
                "Countries",
                f"SELECT now() AS \"time\", COUNT(DISTINCT country) AS value FROM glohydrores.plants_dashboard WHERE {filter_sql}",
                {"h": 4, "w": 6, "x": 12, "y": 0},
                "none",
            ),
            stat_panel(
                4,
                "Distinct Reservoirs",
                f"SELECT now() AS \"time\", COUNT(DISTINCT reservoir_name) AS value FROM glohydrores.plants_dashboard WHERE {filter_sql} AND reservoir_name IS NOT NULL",
                {"h": 4, "w": 6, "x": 18, "y": 0},
                "none",
            ),
            geomap_panel(
                5,
                "Hydro Plants Map",
                (
                    "SELECT 0 AS \"time\", map_lat AS lat, map_lon AS lon, plant_name, country, plant_type, "
                    "capacity_mw, commissioning_year, coordinate_source, reservoir_name, river, head_m, "
                    "dam_height_m, reservoir_area_km2, reservoir_volume_km3 "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} AND map_lat IS NOT NULL AND map_lon IS NOT NULL "
                    "ORDER BY capacity_mw DESC"
                ),
                {"h": 12, "w": 14, "x": 0, "y": 4},
            ),
            bar_chart_panel(
                6,
                "Capacity by Country",
                (
                    "SELECT country, ROUND(SUM(capacity_mw)::numeric, 1) AS \"Capacity MW\" "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} "
                    "GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
                ),
                {"h": 6, "w": 10, "x": 14, "y": 4},
                "country",
            ),
            bar_chart_panel(
                7,
                "Capacity by Plant Type",
                (
                    "SELECT plant_type, ROUND(SUM(capacity_mw)::numeric, 1) AS \"Capacity MW\", COUNT(*) AS \"Plants\" "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} "
                    "GROUP BY 1 ORDER BY 2 DESC"
                ),
                {"h": 6, "w": 10, "x": 14, "y": 10},
                "plant_type",
            ),
            bar_chart_panel(
                8,
                "Build-out by Decade",
                (
                    "SELECT commissioning_decade::text AS decade, "
                    "ROUND(SUM(capacity_mw)::numeric, 1) AS \"Capacity MW\", "
                    "COUNT(*) AS \"Plants\" "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} AND commissioning_decade IS NOT NULL "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"h": 7, "w": 8, "x": 0, "y": 16},
                "decade",
            ),
            bar_chart_panel(
                9,
                "Head Classes",
                (
                    "SELECT head_band, plants AS \"Plants\" "
                    "FROM ("
                    "SELECT CASE "
                    "WHEN head_m IS NULL THEN 'Unknown' "
                    "WHEN head_m < 30 THEN '<30 m' "
                    "WHEN head_m < 100 THEN '30-100 m' "
                    "WHEN head_m < 300 THEN '100-300 m' "
                    "ELSE '>=300 m' END AS head_band, "
                    "CASE "
                    "WHEN head_m IS NULL THEN 5 "
                    "WHEN head_m < 30 THEN 1 "
                    "WHEN head_m < 100 THEN 2 "
                    "WHEN head_m < 300 THEN 3 "
                    "ELSE 4 END AS sort_key, "
                    "COUNT(*) AS plants "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} "
                    "GROUP BY 1, 2"
                    ") s ORDER BY sort_key"
                ),
                {"h": 7, "w": 8, "x": 8, "y": 16},
                "head_band",
            ),
            table_panel(
                10,
                "Largest Hydro Plants",
                (
                    "SELECT plant_name, country, plant_type, ROUND(capacity_mw::numeric, 1) AS capacity_mw, "
                    "commissioning_year, reservoir_name, ROUND(head_m::numeric, 1) AS head_m "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} "
                    "ORDER BY capacity_mw DESC NULLS LAST LIMIT 20"
                ),
                {"h": 7, "w": 8, "x": 16, "y": 16},
            ),
            table_panel(
                11,
                "Largest Reservoir Links",
                (
                    "SELECT COALESCE(reservoir_name, dam_name, plant_name) AS reservoir_or_dam, "
                    "country, plant_name, ROUND(reservoir_volume_km3::numeric, 3) AS reservoir_volume_km3, "
                    "ROUND(reservoir_area_km2::numeric, 2) AS reservoir_area_km2, "
                    "ROUND(reservoir_avg_depth_m::numeric, 1) AS reservoir_avg_depth_m, "
                    "ROUND(capacity_mw::numeric, 1) AS capacity_mw "
                    "FROM glohydrores.plants_dashboard "
                    f"WHERE {filter_sql} AND (reservoir_volume_km3 IS NOT NULL OR reservoir_area_km2 IS NOT NULL) "
                    "ORDER BY reservoir_volume_km3 DESC NULLS LAST, reservoir_area_km2 DESC NULLS LAST LIMIT 25"
                ),
                {"h": 8, "w": 24, "x": 0, "y": 23},
            ),
        ],
        "refresh": "",
        "schemaVersion": 40,
        "style": "dark",
        "tags": ["hydro", "reservoirs", "glohydrores", "oeds"],
        "templating": {
            "list": [
                {
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "SELECT DISTINCT country FROM glohydrores.plants_dashboard ORDER BY 1",
                    "includeAll": True,
                    "label": "Country",
                    "multi": True,
                    "name": "Country",
                    "options": [],
                    "query": "SELECT DISTINCT country FROM glohydrores.plants_dashboard ORDER BY 1",
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
                {
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "SELECT DISTINCT plant_type FROM glohydrores.plants_dashboard ORDER BY 1",
                    "includeAll": True,
                    "label": "Plant Type",
                    "multi": True,
                    "name": "Plant_Type",
                    "options": [],
                    "query": "SELECT DISTINCT plant_type FROM glohydrores.plants_dashboard ORDER BY 1",
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
            ]
        },
        "time": {"from": "now-30d", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "GloHydroRes Hydro Plants & Reservoirs",
        "uid": "glohydrores-hydro",
        "version": 1,
        "weekStart": "",
    }

    OUTFILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTFILE.open("w", encoding="utf-8") as handle:
        json.dump(dashboard, handle, indent=4)
        handle.write("\n")

    print(f"Wrote {OUTFILE}")


if __name__ == "__main__":
    main()
