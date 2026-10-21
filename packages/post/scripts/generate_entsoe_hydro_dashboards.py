"""Generate ENTSO-E hydro dashboards for Grafana."""

from __future__ import annotations

import json
from pathlib import Path


DATASOURCE_UID = "P6EAA63344BCC9F38"
OUT_OVERVIEW = Path("data/provisioning/grafana/dashboards/entsoe_fms/ENTSOE_Hydro_Overview_Structure.json")
OUT_FLEX = Path("data/provisioning/grafana/dashboards/entsoe_fms/ENTSOE_Hydro_Flexibility_Markets.json")

HYDRO_TYPES_SQL = "('Hydro Pumped Storage', 'Hydro Run-of-river and poundage', 'Hydro Water Reservoir')"
PRICE_FILTER_SQL = "\"AreaTypeCode\" = 'BZN' AND (TRIM(COALESCE(\"Sequence\", '')) = '' OR \"Sequence\" = '1')"
CONSUMPTION_EXPR = "CASE WHEN \"ActualConsumption[MW]\"::text = 'NaN' THEN NULL ELSE \"ActualConsumption[MW]\" END"
TIME_BUCKET_TEMPLATE = (
    "to_timestamp("
    "floor(extract(epoch from {column}) * 1000 / GREATEST($__interval_ms, 60000)) "
    "* GREATEST($__interval_ms, 60000) / 1000.0)"
)

AREA_NAME_TO_COUNTRY_SQL = """
CASE
    WHEN area_name = 'Czech Republic (CZ)' THEN 'Czechia'
    WHEN area_name = 'Bosnia and Herz. (BA)' THEN 'Bosnia and Herzegovina'
    WHEN area_name IN ('United Kingdom (UK)', 'GB', 'NIE') THEN 'United Kingdom'
    WHEN area_name IN ('IE(SEM)', 'Ireland (IE)') THEN 'Ireland'
    WHEN area_name IN ('DE-LU', 'DE-AT-LU', 'Germany (DE)') OR area_name LIKE 'DE(%' THEN 'Germany'
    WHEN area_name IN ('DK', 'Denmark (DK)', 'DK1', 'DK2') THEN 'Denmark'
    WHEN area_name = 'Italy (IT)' OR area_name LIKE 'IT-%' THEN 'Italy'
    WHEN area_name = 'Norway (NO)' OR area_name ~ '^NO[1-5]$' THEN 'Norway'
    WHEN area_name = 'Sweden (SE)' OR area_name ~ '^SE[1-4]$' THEN 'Sweden'
    ELSE REGEXP_REPLACE(area_name, ' \\([A-Z]{2,3}\\)$', '')
END
""".strip()


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
        "targets": [{"editorMode": "code", "format": "time_series", "rawQuery": True, "rawSql": raw_sql, "refId": "A"}],
        "title": title,
        "type": "stat",
    }


def timeseries_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    unit: str = "short",
    stack_mode: str = "none",
    description: str = "Source: ENTSO-E.",
    overrides: list[dict] | None = None,
) -> dict:
    return {
        "datasource": datasource(),
        "description": description,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": "",
                    "axisPlacement": "auto",
                    "barAlignment": 0,
                    "barWidthFactor": 0.6,
                    "drawStyle": "line",
                    "fillOpacity": 10 if stack_mode != "none" else 0,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "insertNulls": False,
                    "lineInterpolation": "linear",
                    "lineWidth": 2,
                    "pointSize": 4,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "auto",
                    "spanNulls": False,
                    "stacking": {"group": "A", "mode": stack_mode},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": unit,
            },
            "overrides": overrides or [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"},
        },
        "pluginVersion": "11.3.1",
        "targets": [{"editorMode": "code", "format": "time_series", "rawQuery": True, "rawSql": raw_sql, "refId": "A"}],
        "title": title,
        "type": "timeseries",
    }


def barchart_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    x_field: str,
    description: str = "Source: ENTSO-E.",
) -> dict:
    return {
        "datasource": datasource(),
        "description": description,
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
            "barWidth": 0.88,
            "colorByField": "",
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
        "targets": [{"editorMode": "code", "format": "table", "rawQuery": True, "rawSql": raw_sql, "refId": "A"}],
        "title": title,
        "type": "barchart",
    }


def table_panel(panel_id: int, title: str, raw_sql: str, grid_pos: dict, description: str = "Source: ENTSO-E.") -> dict:
    return {
        "datasource": datasource(),
        "description": description,
        "fieldConfig": {
            "defaults": {"mappings": [], "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}},
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "cellHeight": "sm",
            "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
            "showHeader": True,
        },
        "pluginVersion": "11.3.1",
        "targets": [{"editorMode": "code", "format": "table", "rawQuery": True, "rawSql": raw_sql, "refId": "A"}],
        "title": title,
        "type": "table",
    }


def geomap_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    value_field: str,
    unit: str = "megwatt",
    description: str = "Source: ENTSO-E.",
) -> dict:
    return {
        "datasource": datasource(),
        "description": description,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "continuous-YlRd"},
                "decimals": 1,
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": unit,
            },
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "basemap": {"config": {"showLabels": True, "theme": "auto"}, "name": "Layer 0", "type": "carto"},
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
                            "color": {"field": value_field},
                            "opacity": 0.9,
                            "rotation": {"fixed": 0, "max": 360, "min": -360, "mode": "mod"},
                            "size": {"field": value_field, "fixed": 10, "max": 24, "min": 7},
                            "symbol": {"field": "", "fixed": "img/icons/marker/circle.svg", "mode": "fixed"},
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
            "view": {"allLayers": True, "id": "europe", "lat": 50, "lon": 10, "zoom": 3},
        },
        "pluginVersion": "11.3.1",
        "targets": [{"editorMode": "code", "format": "table", "rawQuery": True, "rawSql": raw_sql, "refId": "A"}],
        "title": title,
        "type": "geomap",
    }


def time_bucket(column: str) -> str:
    return TIME_BUCKET_TEMPLATE.format(column=column)


SELECTED_HYDRO_AREA_TYPE_CTE = f"""
preferred_hydro_area_type AS (
    SELECT area_type
    FROM (
        SELECT
            "AreaTypeCode" AS area_type,
            MAX("DateTime(UTC)") AS latest_ts,
            CASE
                WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
                WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
                WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
                ELSE 9
            END AS priority
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "ProductionType" IN {HYDRO_TYPES_SQL}
          AND "DateTime(UTC)" >= now() - interval '30 days'
        GROUP BY 1, 3
    ) ranked
    ORDER BY priority, latest_ts DESC
    LIMIT 1
)
""".strip()

SELECTED_INSTALLED_AREA_TYPE_CTE = f"""
preferred_installed_area_type AS (
    SELECT area_type
    FROM (
        SELECT
            "AreaTypeCode" AS area_type,
            MAX("Year") AS latest_year,
            CASE
                WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
                WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
                WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
                ELSE 9
            END AS priority
        FROM entsoe_fms."InstalledGenerationCapacityAggregated"
        WHERE "AreaDisplayName" = '$Country'
          AND "ProductionType" IN {HYDRO_TYPES_SQL}
        GROUP BY 1, 3
    ) ranked
    ORDER BY priority, latest_year DESC
    LIMIT 1
)
""".strip()

SELECTED_GENERATION_AREA_TYPE_CTE = """
preferred_generation_area_type AS (
    SELECT area_type
    FROM (
        SELECT
            "AreaTypeCode" AS area_type,
            MAX("DateTime(UTC)") AS latest_ts,
            CASE
                WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
                WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
                WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
                ELSE 9
            END AS priority
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '30 days'
        GROUP BY 1, 3
    ) ranked
    ORDER BY priority, latest_ts DESC
    LIMIT 1
)
""".strip()

SELECTED_LOAD_AREA_TYPE_CTE = """
preferred_load_area_type AS (
    SELECT area_type
    FROM (
        SELECT
            "AreaTypeCode" AS area_type,
            MAX("DateTime(UTC)") AS latest_ts,
            CASE
                WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
                WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
                WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
                ELSE 9
            END AS priority
        FROM entsoe_fms."ActualTotalLoad"
        WHERE "AreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '30 days'
        GROUP BY 1, 3
    ) ranked
    ORDER BY priority, latest_ts DESC
    LIMIT 1
)
""".strip()

ALL_HYDRO_AREA_TYPES_CTE = f"""
hydro_candidates AS (
    SELECT
        "AreaDisplayName" AS area_name,
        "AreaTypeCode" AS area_type,
        MAX("DateTime(UTC)") AS latest_ts,
        CASE
            WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
            WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
            WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
            ELSE 9
        END AS priority
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= now() - interval '30 days'
    GROUP BY 1, 2, 4
),
preferred_hydro_area_types AS (
    SELECT area_name, area_type
    FROM (
        SELECT
            area_name,
            area_type,
            latest_ts,
            priority,
            ROW_NUMBER() OVER (PARTITION BY area_name ORDER BY priority, latest_ts DESC) AS rn
        FROM hydro_candidates
    ) ranked
    WHERE rn = 1
)
""".strip()

ALL_INSTALLED_AREA_TYPES_CTE = f"""
installed_candidates AS (
    SELECT
        "AreaDisplayName" AS area_name,
        "AreaTypeCode" AS area_type,
        MAX("Year") AS latest_year,
        CASE
            WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 1
            WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 2
            WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 3
            ELSE 9
        END AS priority
    FROM entsoe_fms."InstalledGenerationCapacityAggregated"
    WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1, 2, 4
),
preferred_installed_area_types AS (
    SELECT area_name, area_type
    FROM (
        SELECT
            area_name,
            area_type,
            latest_year,
            priority,
            ROW_NUMBER() OVER (PARTITION BY area_name ORDER BY priority, latest_year DESC) AS rn
        FROM installed_candidates
    ) ranked
    WHERE rn = 1
)
""".strip()


def overview_dashboard() -> dict:
    latest_hydro_generation = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
latest_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= now() - interval '3 days'
)
SELECT now() AS "time", SUM("ActualGenerationOutput[MW]") AS value
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
  AND "ProductionType" IN {HYDRO_TYPES_SQL}
  AND "DateTime(UTC)" = (SELECT ts FROM latest_ts)
""".strip()

    hydro_share = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
latest_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "DateTime(UTC)" >= now() - interval '3 days'
),
snapshot AS (
    SELECT
        SUM(CASE WHEN "ProductionType" IN {HYDRO_TYPES_SQL} THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS hydro_mw,
        SUM("ActualGenerationOutput[MW]") AS total_gen_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "DateTime(UTC)" = (SELECT ts FROM latest_ts)
)
SELECT now() AS "time", 100.0 * hydro_mw / NULLIF(total_gen_mw, 0) AS value
FROM snapshot
""".strip()

    installed_capacity = f"""
WITH {SELECTED_INSTALLED_AREA_TYPE_CTE},
latest_year AS (
    SELECT MAX("Year") AS year
    FROM entsoe_fms."InstalledGenerationCapacityAggregated"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
)
SELECT now() AS "time", SUM("AggregatedInstalledCapacity[MW]") AS value
FROM entsoe_fms."InstalledGenerationCapacityAggregated"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
  AND "ProductionType" IN {HYDRO_TYPES_SQL}
  AND "Year" = (SELECT year FROM latest_year)
""".strip()

    utilization = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
{SELECTED_INSTALLED_AREA_TYPE_CTE},
latest_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= now() - interval '3 days'
),
hydro_now AS (
    SELECT SUM("ActualGenerationOutput[MW]") AS hydro_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" = (SELECT ts FROM latest_ts)
),
latest_year AS (
    SELECT MAX("Year") AS year
    FROM entsoe_fms."InstalledGenerationCapacityAggregated"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
),
installed AS (
    SELECT SUM("AggregatedInstalledCapacity[MW]") AS installed_mw
    FROM entsoe_fms."InstalledGenerationCapacityAggregated"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "Year" = (SELECT year FROM latest_year)
)
SELECT now() AS "time", 100.0 * hydro_mw / NULLIF(installed_mw, 0) AS value
FROM hydro_now CROSS JOIN installed
""".strip()

    generation_by_type = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE}
SELECT {time_bucket('my_time')} AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT
        "DateTime(UTC)" AS my_time,
        CASE "ProductionType"
            WHEN 'Hydro Pumped Storage' THEN 'Pumped Storage'
            WHEN 'Hydro Run-of-river and poundage' THEN 'Run-of-river'
            WHEN 'Hydro Water Reservoir' THEN 'Water Reservoir'
        END AS metric,
        "ActualGenerationOutput[MW]" AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
) s
GROUP BY 1, 2
ORDER BY 1
""".strip()

    current_hydro_map = f"""
WITH {ALL_HYDRO_AREA_TYPES_CTE},
latest_ts AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        MAX(g."DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    WHERE g."ProductionType" IN {HYDRO_TYPES_SQL}
      AND g."DateTime(UTC)" >= now() - interval '3 days'
    GROUP BY 1
),
hydro_snapshot AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        SUM(g."ActualGenerationOutput[MW]") AS hydro_mw,
        MAX(g."DateTime(UTC)") AS snapshot_time
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    JOIN latest_ts lt
      ON lt.area_name = g."AreaDisplayName"
     AND lt.ts = g."DateTime(UTC)"
    WHERE g."ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1
),
mapped AS (
    SELECT
        area_name,
        hydro_mw,
        snapshot_time,
        {AREA_NAME_TO_COUNTRY_SQL} AS mapped_country
    FROM hydro_snapshot
),
country_centroids AS (
    SELECT country, AVG(lat) AS lat, AVG(lon) AS lon
    FROM entsoe_fms.powersystemdata
    WHERE lat IS NOT NULL AND lon IS NOT NULL
    GROUP BY 1
)
SELECT
    0 AS "time",
    cc.lat,
    cc.lon,
    m.area_name AS name,
    m.area_name AS country,
    ROUND(m.hydro_mw::numeric, 1) AS hydro_mw,
    m.snapshot_time
FROM mapped m
JOIN country_centroids cc
  ON cc.country = m.mapped_country
ORDER BY hydro_mw DESC
""".strip()

    capacity_by_country = f"""
WITH {ALL_INSTALLED_AREA_TYPES_CTE},
latest_year AS (
    SELECT
        i."AreaDisplayName" AS area_name,
        MAX(i."Year") AS year
    FROM entsoe_fms."InstalledGenerationCapacityAggregated" i
    JOIN preferred_installed_area_types p
      ON p.area_name = i."AreaDisplayName"
     AND p.area_type = i."AreaTypeCode"
    WHERE i."ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1
)
SELECT
    i."AreaDisplayName" AS country,
    ROUND(SUM(i."AggregatedInstalledCapacity[MW]")::numeric, 1) AS "Installed Hydro MW"
FROM entsoe_fms."InstalledGenerationCapacityAggregated" i
JOIN preferred_installed_area_types p
  ON p.area_name = i."AreaDisplayName"
 AND p.area_type = i."AreaTypeCode"
JOIN latest_year y
  ON y.area_name = i."AreaDisplayName"
 AND y.year = i."Year"
WHERE i."ProductionType" IN {HYDRO_TYPES_SQL}
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20
""".strip()

    hydro_structure = f"""
WITH {SELECTED_INSTALLED_AREA_TYPE_CTE},
latest_year AS (
    SELECT MAX("Year") AS year
    FROM entsoe_fms."InstalledGenerationCapacityAggregated"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
)
SELECT
    CASE "ProductionType"
        WHEN 'Hydro Pumped Storage' THEN 'Pumped Storage'
        WHEN 'Hydro Run-of-river and poundage' THEN 'Run-of-river'
        WHEN 'Hydro Water Reservoir' THEN 'Water Reservoir'
    END AS hydro_type,
    ROUND(SUM("AggregatedInstalledCapacity[MW]")::numeric, 1) AS "Installed MW"
FROM entsoe_fms."InstalledGenerationCapacityAggregated"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_installed_area_type)
  AND "ProductionType" IN {HYDRO_TYPES_SQL}
  AND "Year" = (SELECT year FROM latest_year)
GROUP BY 1
ORDER BY 2 DESC
""".strip()

    monthly_profile = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE}
SELECT
    LPAD(EXTRACT(MONTH FROM "DateTime(UTC)")::int::text, 2, '0') || ' ' || TO_CHAR("DateTime(UTC)", 'Mon') AS month,
    ROUND(AVG(CASE WHEN "ProductionType" = 'Hydro Run-of-river and poundage' THEN "ActualGenerationOutput[MW]" END)::numeric, 1) AS "Run-of-river",
    ROUND(AVG(CASE WHEN "ProductionType" = 'Hydro Water Reservoir' THEN "ActualGenerationOutput[MW]" END)::numeric, 1) AS "Water Reservoir",
    ROUND(AVG(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN "ActualGenerationOutput[MW]" END)::numeric, 1) AS "Pumped Storage"
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
  AND "ProductionType" IN {HYDRO_TYPES_SQL}
GROUP BY EXTRACT(MONTH FROM "DateTime(UTC)")::int, month
ORDER BY EXTRACT(MONTH FROM MIN("DateTime(UTC)"))::int
""".strip()

    country_snapshot = f"""
WITH {ALL_HYDRO_AREA_TYPES_CTE},
latest_ts AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        MAX(g."DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    WHERE g."ProductionType" IN {HYDRO_TYPES_SQL}
      AND g."DateTime(UTC)" >= now() - interval '3 days'
    GROUP BY 1
),
hydro_snapshot AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        SUM(g."ActualGenerationOutput[MW]") AS hydro_mw
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    JOIN latest_ts lt
      ON lt.area_name = g."AreaDisplayName"
     AND lt.ts = g."DateTime(UTC)"
    WHERE g."ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1
),
total_generation AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        SUM(g."ActualGenerationOutput[MW]") AS total_gen_mw
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    JOIN latest_ts lt
      ON lt.area_name = g."AreaDisplayName"
     AND lt.ts = g."DateTime(UTC)"
    GROUP BY 1
),
{ALL_INSTALLED_AREA_TYPES_CTE},
latest_year AS (
    SELECT
        i."AreaDisplayName" AS area_name,
        MAX(i."Year") AS year
    FROM entsoe_fms."InstalledGenerationCapacityAggregated" i
    JOIN preferred_installed_area_types p
      ON p.area_name = i."AreaDisplayName"
     AND p.area_type = i."AreaTypeCode"
    WHERE i."ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1
),
installed_snapshot AS (
    SELECT
        i."AreaDisplayName" AS area_name,
        SUM(i."AggregatedInstalledCapacity[MW]") AS installed_hydro_mw
    FROM entsoe_fms."InstalledGenerationCapacityAggregated" i
    JOIN preferred_installed_area_types p
      ON p.area_name = i."AreaDisplayName"
     AND p.area_type = i."AreaTypeCode"
    JOIN latest_year y
      ON y.area_name = i."AreaDisplayName"
     AND y.year = i."Year"
    WHERE i."ProductionType" IN {HYDRO_TYPES_SQL}
    GROUP BY 1
)
SELECT
    h.area_name AS country,
    ROUND(h.hydro_mw::numeric, 1) AS current_hydro_mw,
    ROUND(i.installed_hydro_mw::numeric, 1) AS installed_hydro_mw,
    ROUND((100.0 * h.hydro_mw / NULLIF(i.installed_hydro_mw, 0))::numeric, 1) AS utilization_pct,
    ROUND((100.0 * h.hydro_mw / NULLIF(t.total_gen_mw, 0))::numeric, 1) AS hydro_share_pct
FROM hydro_snapshot h
LEFT JOIN installed_snapshot i ON i.area_name = h.area_name
LEFT JOIN total_generation t ON t.area_name = h.area_name
ORDER BY current_hydro_mw DESC NULLS LAST
LIMIT 25
""".strip()

    return {
        "__inputs": [],
        "__requires": [
            {"type": "datasource", "id": "grafana-postgresql-datasource", "name": "OPENDATA", "version": "1.0.0"},
            {"type": "panel", "id": "stat", "name": "Stat", "version": "11.3.1"},
            {"type": "panel", "id": "timeseries", "name": "Time series", "version": "11.3.1"},
            {"type": "panel", "id": "barchart", "name": "Bar chart", "version": "11.3.1"},
            {"type": "panel", "id": "table", "name": "Table", "version": "11.3.1"},
            {"type": "panel", "id": "geomap", "name": "Geomap", "version": "11.3.1"},
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
        "description": "Source: ENTSO-E. Hydro overview, structure, utilization, and seasonality.",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "liveNow": False,
        "panels": [
            stat_panel(1, "Current Hydro Generation", latest_hydro_generation, {"h": 4, "w": 6, "x": 0, "y": 0}, "megwatt", 1),
            stat_panel(2, "Hydro Share of Generation", hydro_share, {"h": 4, "w": 6, "x": 6, "y": 0}, "percent", 1),
            stat_panel(3, "Installed Hydro Capacity", installed_capacity, {"h": 4, "w": 6, "x": 12, "y": 0}, "megwatt", 1),
            stat_panel(4, "Current Utilization", utilization, {"h": 4, "w": 6, "x": 18, "y": 0}, "percent", 1),
            timeseries_panel(5, "Hydro Generation by Type", generation_by_type, {"h": 8, "w": 14, "x": 0, "y": 4}, unit="megwatt", stack_mode="normal"),
            geomap_panel(6, "Current Hydro Output Map", current_hydro_map, {"h": 8, "w": 10, "x": 14, "y": 4}, "hydro_mw"),
            barchart_panel(7, "Installed Hydro Capacity by Country", capacity_by_country, {"h": 7, "w": 10, "x": 0, "y": 12}, "country"),
            barchart_panel(8, "Hydro Structure in Selected Country", hydro_structure, {"h": 7, "w": 6, "x": 10, "y": 12}, "hydro_type"),
            barchart_panel(9, "Monthly Hydro Profile", monthly_profile, {"h": 7, "w": 8, "x": 16, "y": 12}, "month"),
            table_panel(10, "Country Hydro Snapshot", country_snapshot, {"h": 8, "w": 24, "x": 0, "y": 19}),
        ],
        "refresh": "5m",
        "schemaVersion": 40,
        "style": "dark",
        "tags": ["entsoe", "hydro", "oeds", "overview"],
        "templating": {
            "list": [
                {
                    "current": {"text": "DE-LU", "value": "DE-LU"},
                    "definition": f"""
SELECT DISTINCT "AreaDisplayName"
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
  AND "DateTime(UTC)" >= now() - interval '30 days'
ORDER BY 1
""".strip(),
                    "label": "Country / Zone",
                    "name": "Country",
                    "options": [],
                    "query": f"""
SELECT DISTINCT "AreaDisplayName"
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
  AND "DateTime(UTC)" >= now() - interval '30 days'
ORDER BY 1
""".strip(),
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                }
            ]
        },
        "time": {"from": "now-30d", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "ENTSOE Hydro Overview & Structure",
        "uid": "entsoe-hydro-overview",
        "version": 1,
        "weekStart": "",
    }


def flexibility_dashboard() -> dict:
    latest_ps_generation = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
latest_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" = 'Hydro Pumped Storage'
      AND "DateTime(UTC)" >= now() - interval '3 days'
)
SELECT now() AS "time", SUM("ActualGenerationOutput[MW]") AS value
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
  AND "ProductionType" = 'Hydro Pumped Storage'
  AND "DateTime(UTC)" = (SELECT ts FROM latest_ts)
""".strip()

    latest_ps_consumption = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
latest_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" = 'Hydro Pumped Storage'
      AND "DateTime(UTC)" >= now() - interval '3 days'
)
SELECT now() AS "time", SUM({CONSUMPTION_EXPR}) AS value
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
  AND "ProductionType" = 'Hydro Pumped Storage'
  AND "DateTime(UTC)" = (SELECT ts FROM latest_ts)
""".strip()

    latest_residual_load = f"""
WITH {SELECTED_LOAD_AREA_TYPE_CTE},
{SELECTED_GENERATION_AREA_TYPE_CTE},
latest_load_ts AS (
    SELECT MAX("DateTime(UTC)") AS ts
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_load_area_type)
      AND "DateTime(UTC)" >= now() - interval '3 days'
),
load_snapshot AS (
    SELECT "TotalLoad[MW]" AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_load_area_type)
      AND "DateTime(UTC)" = (SELECT ts FROM latest_load_ts)
),
vres_snapshot AS (
    SELECT SUM("ActualGenerationOutput[MW]") AS vres_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_generation_area_type)
      AND "DateTime(UTC)" = (SELECT ts FROM latest_load_ts)
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
)
SELECT now() AS "time", load_mw - COALESCE(vres_mw, 0) AS value
FROM load_snapshot CROSS JOIN vres_snapshot
""".strip()

    latest_price = f"""
SELECT now() AS "time", "Price[Currency/MWh]" AS value
FROM entsoe_fms."EnergyPrices"
WHERE "AreaDisplayName" = '$Country'
  AND {PRICE_FILTER_SQL}
  AND "DateTime(UTC)" >= now() - interval '3 days'
ORDER BY "DateTime(UTC)" DESC
LIMIT 1
""".strip()

    dispatch_and_pumping = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE}
SELECT {time_bucket('ts')} AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT
        "DateTime(UTC)" AS ts,
        CASE "ProductionType"
            WHEN 'Hydro Run-of-river and poundage' THEN 'Run-of-river'
            WHEN 'Hydro Water Reservoir' THEN 'Water Reservoir'
            WHEN 'Hydro Pumped Storage' THEN 'Pumped Storage Generation'
        END AS metric,
        "ActualGenerationOutput[MW]" AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
    UNION ALL
    SELECT
        "DateTime(UTC)" AS ts,
        'Pumping Consumption' AS metric,
        -1 * {CONSUMPTION_EXPR} AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" = 'Hydro Pumped Storage'
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
) s
GROUP BY 1, 2
ORDER BY 1
""".strip()

    hydro_vs_residual = f"""
WITH {SELECTED_LOAD_AREA_TYPE_CTE},
{SELECTED_GENERATION_AREA_TYPE_CTE},
load_ts AS (
    SELECT
        "DateTime(UTC)" AS ts,
        "TotalLoad[MW]" AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_load_area_type)
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
),
generation_ts AS (
    SELECT
        "DateTime(UTC)" AS ts,
        SUM(CASE WHEN "ProductionType" IN {HYDRO_TYPES_SQL} THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS hydro_total_mw,
        SUM(CASE WHEN "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore') THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS vres_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_generation_area_type)
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
    GROUP BY 1
)
SELECT {time_bucket('ts')} AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT l.ts, 'Hydro Total' AS metric, g.hydro_total_mw AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Residual Load' AS metric, l.load_mw - COALESCE(g.vres_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Total Load' AS metric, l.load_mw AS value
    FROM load_ts l
) s
GROUP BY 1, 2
ORDER BY 1
""".strip()

    hourly_cycle = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE}
SELECT
    EXTRACT(HOUR FROM "DateTime(UTC)")::int AS hour_utc,
    ROUND(AVG("ActualGenerationOutput[MW]")::numeric, 1) AS "Generation MW",
    ROUND(AVG({CONSUMPTION_EXPR})::numeric, 1) AS "Pumping MW",
    ROUND(AVG("ActualGenerationOutput[MW]" - COALESCE({CONSUMPTION_EXPR}, 0))::numeric, 1) AS "Net MW"
FROM entsoe_fms."AggregatedGenerationPerType"
WHERE "AreaDisplayName" = '$Country'
  AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
  AND "ProductionType" = 'Hydro Pumped Storage'
  AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
  AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
GROUP BY 1
ORDER BY 1
""".strip()

    price_band_dispatch = f"""
WITH {SELECTED_HYDRO_AREA_TYPE_CTE},
hydro_ts AS (
    SELECT
        "DateTime(UTC)" AS ts,
        SUM("ActualGenerationOutput[MW]") AS hydro_total_mw,
        SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS ps_generation_mw,
        SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN COALESCE({CONSUMPTION_EXPR}, 0) ELSE 0 END) AS ps_consumption_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_hydro_area_type)
      AND "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
    GROUP BY 1
),
prices AS (
    SELECT
        "DateTime(UTC)" AS ts,
        "Price[Currency/MWh]" AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
),
joined AS (
    SELECT
        h.ts,
        h.hydro_total_mw,
        h.ps_generation_mw,
        h.ps_consumption_mw,
        CASE
            WHEN p.price_mwh < 0 THEN '1 <0'
            WHEN p.price_mwh < 25 THEN '2 0-25'
            WHEN p.price_mwh < 50 THEN '3 25-50'
            WHEN p.price_mwh < 100 THEN '4 50-100'
            WHEN p.price_mwh < 200 THEN '5 100-200'
            ELSE '6 >=200'
        END AS price_band
    FROM hydro_ts h
    JOIN prices p ON p.ts = h.ts
)
SELECT
    price_band,
    ROUND(AVG(hydro_total_mw)::numeric, 1) AS "Hydro Total MW",
    ROUND(AVG(ps_generation_mw)::numeric, 1) AS "Pumped Generation MW",
    ROUND(AVG(ps_consumption_mw)::numeric, 1) AS "Pumping MW"
FROM joined
GROUP BY 1
ORDER BY 1
""".strip()

    current_ps_map = f"""
WITH {ALL_HYDRO_AREA_TYPES_CTE},
latest_ts AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        MAX(g."DateTime(UTC)") AS ts
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    WHERE g."ProductionType" = 'Hydro Pumped Storage'
      AND g."DateTime(UTC)" >= now() - interval '3 days'
    GROUP BY 1
),
ps_snapshot AS (
    SELECT
        g."AreaDisplayName" AS area_name,
        SUM(g."ActualGenerationOutput[MW]") AS ps_generation_mw,
        SUM(COALESCE({CONSUMPTION_EXPR}, 0)) AS ps_consumption_mw,
        MAX(g."DateTime(UTC)") AS snapshot_time
    FROM entsoe_fms."AggregatedGenerationPerType" g
    JOIN preferred_hydro_area_types p
      ON p.area_name = g."AreaDisplayName"
     AND p.area_type = g."AreaTypeCode"
    JOIN latest_ts lt
      ON lt.area_name = g."AreaDisplayName"
     AND lt.ts = g."DateTime(UTC)"
    WHERE g."ProductionType" = 'Hydro Pumped Storage'
    GROUP BY 1
),
mapped AS (
    SELECT
        area_name,
        ps_generation_mw,
        ps_consumption_mw,
        snapshot_time,
        {AREA_NAME_TO_COUNTRY_SQL} AS mapped_country
    FROM ps_snapshot
),
country_centroids AS (
    SELECT country, AVG(lat) AS lat, AVG(lon) AS lon
    FROM entsoe_fms.powersystemdata
    WHERE lat IS NOT NULL AND lon IS NOT NULL
    GROUP BY 1
)
SELECT
    0 AS "time",
    cc.lat,
    cc.lon,
    m.area_name AS name,
    m.area_name AS country,
    ROUND(m.ps_generation_mw::numeric, 1) AS ps_generation_mw,
    ROUND(m.ps_consumption_mw::numeric, 1) AS ps_consumption_mw,
    m.snapshot_time
FROM mapped m
JOIN country_centroids cc
  ON cc.country = m.mapped_country
ORDER BY ps_generation_mw DESC
""".strip()

    daily_summary = f"""
WITH {SELECTED_LOAD_AREA_TYPE_CTE},
{SELECTED_GENERATION_AREA_TYPE_CTE},
load_ts AS (
    SELECT
        "DateTime(UTC)" AS ts,
        "TotalLoad[MW]" AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_load_area_type)
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
),
generation_ts AS (
    SELECT
        "DateTime(UTC)" AS ts,
        SUM(CASE WHEN "ProductionType" IN {HYDRO_TYPES_SQL} THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS hydro_total_mw,
        SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS ps_generation_mw,
        SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN COALESCE({CONSUMPTION_EXPR}, 0) ELSE 0 END) AS ps_consumption_mw,
        SUM(CASE WHEN "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore') THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS vres_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = (SELECT area_type FROM preferred_generation_area_type)
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
    GROUP BY 1
),
prices AS (
    SELECT
        "DateTime(UTC)" AS ts,
        "Price[Currency/MWh]" AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= to_timestamp($__from / 1000.0)
      AND "DateTime(UTC)" <= to_timestamp($__to / 1000.0)
)
SELECT
    date_trunc('day', l.ts) AS day,
    TO_CHAR(date_trunc('day', l.ts), 'Dy') AS weekday,
    ROUND(AVG(g.hydro_total_mw)::numeric, 1) AS avg_hydro_total_mw,
    ROUND(AVG(g.ps_generation_mw)::numeric, 1) AS avg_ps_generation_mw,
    ROUND(AVG(g.ps_consumption_mw)::numeric, 1) AS avg_pumping_mw,
    ROUND(AVG(l.load_mw - COALESCE(g.vres_mw, 0))::numeric, 1) AS avg_residual_load_mw,
    ROUND(AVG(p.price_mwh)::numeric, 2) AS avg_day_ahead_price_eur_mwh
FROM load_ts l
LEFT JOIN generation_ts g ON g.ts = l.ts
LEFT JOIN prices p ON p.ts = l.ts
GROUP BY 1, 2
ORDER BY 1 DESC
LIMIT 21
""".strip()

    export_window = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '30 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '30 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
latest_home AS (
    SELECT "Price[Currency/MWh]" AS home_price
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= now() - interval '3 days'
    ORDER BY "DateTime(UTC)" DESC
    LIMIT 1
),
latest_nb AS (
    SELECT DISTINCT ON ("AreaDisplayName")
        "AreaDisplayName" AS neighbour,
        "Price[Currency/MWh]" AS neighbour_price
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= now() - interval '3 days'
    ORDER BY "AreaDisplayName", "DateTime(UTC)" DESC
),
export_cap AS (
    SELECT
        "InAreaDisplayName" AS neighbour,
        AVG("ForecastTransferCapacity[MW]") AS export_headroom_mw
    FROM entsoe_fms."ForecastedTransferCapacities"
    WHERE "OutAreaDisplayName" = '$Country'
      AND "ContractType" = '$Transfer_Contract'
      AND "DateTime(UTC)" > now()
      AND "DateTime(UTC)" <= now() + interval '24 hours'
    GROUP BY 1
),
import_cap AS (
    SELECT
        "OutAreaDisplayName" AS neighbour,
        AVG("ForecastTransferCapacity[MW]") AS import_headroom_mw
    FROM entsoe_fms."ForecastedTransferCapacities"
    WHERE "InAreaDisplayName" = '$Country'
      AND "ContractType" = '$Transfer_Contract'
      AND "DateTime(UTC)" > now()
      AND "DateTime(UTC)" <= now() + interval '24 hours'
    GROUP BY 1
)
SELECT
    n.neighbour,
    ROUND(h.home_price::numeric, 2) AS home_price_eur_mwh,
    ROUND(n.neighbour_price::numeric, 2) AS neighbour_price_eur_mwh,
    ROUND((h.home_price - n.neighbour_price)::numeric, 2) AS spread_eur_mwh,
    ROUND(COALESCE(e.export_headroom_mw, 0)::numeric, 1) AS avg_export_headroom_mw,
    ROUND(COALESCE(i.import_headroom_mw, 0)::numeric, 1) AS avg_import_headroom_mw
FROM latest_nb n
CROSS JOIN latest_home h
LEFT JOIN export_cap e ON e.neighbour = n.neighbour
LEFT JOIN import_cap i ON i.neighbour = n.neighbour
ORDER BY spread_eur_mwh DESC, avg_export_headroom_mw DESC
""".strip()

    return {
        "__inputs": [],
        "__requires": [
            {"type": "datasource", "id": "grafana-postgresql-datasource", "name": "OPENDATA", "version": "1.0.0"},
            {"type": "panel", "id": "stat", "name": "Stat", "version": "11.3.1"},
            {"type": "panel", "id": "timeseries", "name": "Time series", "version": "11.3.1"},
            {"type": "panel", "id": "barchart", "name": "Bar chart", "version": "11.3.1"},
            {"type": "panel", "id": "table", "name": "Table", "version": "11.3.1"},
            {"type": "panel", "id": "geomap", "name": "Geomap", "version": "11.3.1"},
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
        "description": "Source: ENTSO-E. Hydro flexibility, pumped storage behavior, residual load, and market context.",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "liveNow": False,
        "panels": [
            stat_panel(1, "Current Pumped Storage Generation", latest_ps_generation, {"h": 4, "w": 6, "x": 0, "y": 0}, "megwatt", 1),
            stat_panel(2, "Current Pumping Consumption", latest_ps_consumption, {"h": 4, "w": 6, "x": 6, "y": 0}, "megwatt", 1),
            stat_panel(3, "Current Residual Load", latest_residual_load, {"h": 4, "w": 6, "x": 12, "y": 0}, "megwatt", 1),
            stat_panel(4, "Latest Day-Ahead Price", latest_price, {"h": 4, "w": 6, "x": 18, "y": 0}, "currencyEUR", 2),
            timeseries_panel(5, "Hydro Dispatch & Pumping", dispatch_and_pumping, {"h": 8, "w": 14, "x": 0, "y": 4}, unit="megwatt"),
            timeseries_panel(6, "Hydro vs Residual Load", hydro_vs_residual, {"h": 8, "w": 10, "x": 14, "y": 4}, unit="megwatt"),
            barchart_panel(7, "Hourly Pumped Storage Cycle", hourly_cycle, {"h": 7, "w": 8, "x": 0, "y": 12}, "hour_utc"),
            barchart_panel(8, "Hydro Dispatch by Price Band", price_band_dispatch, {"h": 7, "w": 8, "x": 8, "y": 12}, "price_band"),
            geomap_panel(9, "Current Pumped Storage Map", current_ps_map, {"h": 7, "w": 8, "x": 16, "y": 12}, "ps_generation_mw"),
            table_panel(10, "Daily Hydro-Market Summary", daily_summary, {"h": 8, "w": 14, "x": 0, "y": 19}),
            table_panel(11, "Cross-Border Export Window Snapshot", export_window, {"h": 8, "w": 10, "x": 14, "y": 19}),
        ],
        "refresh": "5m",
        "schemaVersion": 40,
        "style": "dark",
        "tags": ["entsoe", "hydro", "oeds", "flexibility", "market"],
        "templating": {
            "list": [
                {
                    "current": {"text": "DE-LU", "value": "DE-LU"},
                    "definition": f"""
WITH hydro_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= now() - interval '30 days'
),
price_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."EnergyPrices"
    WHERE {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= now() - interval '30 days'
)
SELECT h.area_name
FROM hydro_areas h
JOIN price_areas p ON p.area_name = h.area_name
ORDER BY 1
""".strip(),
                    "label": "Country / Price Zone",
                    "name": "Country",
                    "options": [],
                    "query": f"""
WITH hydro_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "ProductionType" IN {HYDRO_TYPES_SQL}
      AND "DateTime(UTC)" >= now() - interval '30 days'
),
price_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."EnergyPrices"
    WHERE {PRICE_FILTER_SQL}
      AND "DateTime(UTC)" >= now() - interval '30 days'
)
SELECT h.area_name
FROM hydro_areas h
JOIN price_areas p ON p.area_name = h.area_name
ORDER BY 1
""".strip(),
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "type": "query",
                },
                {
                    "current": {"text": "Day-ahead", "value": "Day-ahead"},
                    "definition": "Day-ahead,Week-ahead,Month-ahead,Year-ahead",
                    "label": "Transfer Contract",
                    "name": "Transfer_Contract",
                    "options": [],
                    "query": "Day-ahead,Week-ahead,Month-ahead,Year-ahead",
                    "refresh": 1,
                    "regex": "",
                    "type": "custom",
                },
            ]
        },
        "time": {"from": "now-14d", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "ENTSOE Hydro Flexibility & Markets",
        "uid": "entsoe-hydro-flex",
        "version": 1,
        "weekStart": "",
    }


def main() -> None:
    OUT_OVERVIEW.parent.mkdir(parents=True, exist_ok=True)
    OUT_OVERVIEW.write_text(json.dumps(overview_dashboard(), indent=4) + "\n", encoding="utf-8")
    OUT_FLEX.write_text(json.dumps(flexibility_dashboard(), indent=4) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_OVERVIEW}")
    print(f"Wrote {OUT_FLEX}")


if __name__ == "__main__":
    main()
