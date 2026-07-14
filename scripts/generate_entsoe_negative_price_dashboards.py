"""Generate ENTSO-E negative-price Grafana dashboards."""

from __future__ import annotations

import json
from pathlib import Path


DATASOURCE_UID = "P6EAA63344BCC9F38"
OUT_EVENT = Path("data/provisioning/grafana/dashboards/entsoe_fms/ENTSOE_Negative_Prices_Event_2026_04_26.json")
OUT_LONG_TERM = Path("data/provisioning/grafana/dashboards/entsoe_fms/ENTSOE_Negative_Prices_Long_Term.json")

EVENT_SUNDAY = "DATE '2026-04-26'"
UNIT_EUR_PER_MWH = "suffix:€/MWh"
UNIT_MWH = "suffix:MWh"
UNIT_HOURS = "suffix:h"
DAY_AHEAD_TRANSFER_CONTRACT = "Day-ahead"

NEGATIVE_PRICE_COUNTRY_QUERY = """
WITH price_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."EnergyPrices"
    WHERE "DateTime(UTC)" >= now() - interval '730 days'
      AND "AreaTypeCode" = 'BZN'
),
load_areas AS (
    SELECT DISTINCT "AreaDisplayName" AS area_name
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "DateTime(UTC)" >= now() - interval '730 days'
)
SELECT p.area_name
FROM price_areas p
JOIN load_areas l ON l.area_name = p.area_name
ORDER BY 1
""".strip()

NEGATIVE_PRICE_AREA_TYPE_QUERY = """
SELECT area_type
FROM (
    SELECT
        "AreaTypeCode" AS area_type,
        MAX("DateTime(UTC)") AS latest_ts,
        CASE
            WHEN "AreaTypeCode" = 'BZN' THEN 1
            WHEN POSITION('BZN' IN "AreaTypeCode") > 0 THEN 2
            WHEN POSITION('CTA' IN "AreaTypeCode") > 0 THEN 3
            WHEN POSITION('CTY' IN "AreaTypeCode") > 0 THEN 4
            ELSE 9
        END AS priority
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "DateTime(UTC)" >= now() - interval '730 days'
      AND "AreaDisplayName" = '$Country'
    GROUP BY 1, 3
) ranked
ORDER BY priority, latest_ts DESC, area_type
""".strip()


def datasource() -> dict:
    return {"type": "grafana-postgresql-datasource", "uid": DATASOURCE_UID}


def base_target(raw_sql: str, *, fmt: str = "time_series") -> dict:
    return {
        "editorMode": "code",
        "format": fmt,
        "rawQuery": True,
        "rawSql": raw_sql,
        "refId": "A",
    }


def stat_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    unit: str,
    *,
    decimals: int = 0,
    description: str | None = None,
) -> dict:
    panel = {
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
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "auto",
            "wideLayout": True,
        },
        "pluginVersion": "11.3.1",
        "targets": [base_target(raw_sql)],
        "title": title,
        "type": "stat",
    }
    if description:
        panel["description"] = description
    return panel


def timeseries_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    *,
    unit: str = "short",
    decimals: int | None = None,
    description: str | None = None,
    stacking: str = "none",
    fill_opacity: int = 10,
    draw_style: str = "line",
    line_width: int = 1,
    bar_width_factor: float | None = None,
    overrides: list[dict] | None = None,
) -> dict:
    defaults: dict = {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisBorderShow": False,
            "axisCenteredZero": False,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": draw_style,
            "fillOpacity": fill_opacity,
            "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "insertNulls": False,
            "lineInterpolation": "linear",
            "lineStyle": {"fill": "solid"},
            "lineWidth": line_width,
            "pointSize": 4,
            "scaleDistribution": {"type": "linear"},
            "showPoints": "never",
            "spanNulls": False,
            "stacking": {"group": "A", "mode": stacking},
            "thresholdsStyle": {"mode": "off"},
        },
        "mappings": [],
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
        "unit": unit,
    }
    if bar_width_factor is not None:
        defaults["custom"]["barWidthFactor"] = bar_width_factor
    if decimals is not None:
        defaults["decimals"] = decimals
    panel = {
        "datasource": datasource(),
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"},
        },
        "pluginVersion": "11.3.1",
        "targets": [base_target(raw_sql)],
        "title": title,
        "type": "timeseries",
    }
    if description:
        panel["description"] = description
    return panel


GENERATION_MIX_OVERRIDES = [
    {"matcher": {"id": "byName", "options": "Biomass"}, "properties": [{"id": "color", "value": {"fixedColor": "#36B24A", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Energy storage"}, "properties": [{"id": "color", "value": {"fixedColor": "#29A8FF", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Brown coal/Lignite"}, "properties": [{"id": "color", "value": {"fixedColor": "#B6A48F", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Coal-derived gas"}, "properties": [{"id": "color", "value": {"fixedColor": "#D4B45D", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Gas"}, "properties": [{"id": "color", "value": {"fixedColor": "#FFB171", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Hard coal"}, "properties": [{"id": "color", "value": {"fixedColor": "#57575D", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Oil"}, "properties": [{"id": "color", "value": {"fixedColor": "#8F7A61", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Oil shale"}, "properties": [{"id": "color", "value": {"fixedColor": "#8F7A61", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Fossil Peat"}, "properties": [{"id": "color", "value": {"fixedColor": "#9A8568", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Geothermal"}, "properties": [{"id": "color", "value": {"fixedColor": "#5B4FC9", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Hydro Pumped Storage"}, "properties": [{"id": "color", "value": {"fixedColor": "#29A8FF", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Hydro Run-of-river and poundage"}, "properties": [{"id": "color", "value": {"fixedColor": "#2F39D0", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Hydro Water Reservoir"}, "properties": [{"id": "color", "value": {"fixedColor": "#B5CBFF", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Marine"}, "properties": [{"id": "color", "value": {"fixedColor": "#4AB8E8", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Nuclear"}, "properties": [{"id": "color", "value": {"fixedColor": "#C85AA5", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Other"}, "properties": [{"id": "color", "value": {"fixedColor": "#8A75B3", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Other renewable"}, "properties": [{"id": "color", "value": {"fixedColor": "#8A75B3", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Solar"}, "properties": [{"id": "color", "value": {"fixedColor": "#FFD676", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Waste"}, "properties": [{"id": "color", "value": {"fixedColor": "#6E4513", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Wind Offshore"}, "properties": [{"id": "color", "value": {"fixedColor": "#97AA96", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Wind Onshore"}, "properties": [{"id": "color", "value": {"fixedColor": "#C9DBBE", "mode": "fixed"}}]},
]


DEMAND_WIND_SOLAR_OVERRIDES = [
    {"matcher": {"id": "byName", "options": "Total Load"}, "properties": [{"id": "color", "value": {"fixedColor": "#1F2937", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Residual Load"}, "properties": [{"id": "color", "value": {"fixedColor": "#4B5563", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Residual Load incl. Trade"}, "properties": [{"id": "color", "value": {"fixedColor": "#0F766E", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Solar"}, "properties": [{"id": "color", "value": {"fixedColor": "#FFD676", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Wind Offshore"}, "properties": [{"id": "color", "value": {"fixedColor": "#97AA96", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Wind Onshore"}, "properties": [{"id": "color", "value": {"fixedColor": "#C9DBBE", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Imports"}, "properties": [{"id": "color", "value": {"fixedColor": "#2563EB", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Exports"}, "properties": [{"id": "color", "value": {"fixedColor": "#DC2626", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Net Export Delta"}, "properties": [{"id": "color", "value": {"fixedColor": "#7C3AED", "mode": "fixed"}}]},
    {"matcher": {"id": "byName", "options": "Net Position"}, "properties": [{"id": "color", "value": {"fixedColor": "#7C3AED", "mode": "fixed"}}]},
]


FORECAST_LINE_OVERRIDES = [
    {
        "matcher": {"id": "byRegexp", "options": "/.* Forecast$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
            {"id": "custom.fillOpacity", "value": 0},
            {"id": "custom.lineWidth", "value": 2},
        ],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/.* Actual$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "solid"}},
            {"id": "custom.lineWidth", "value": 2},
        ],
    },
]


FORECAST_STACK_OVERRIDES = [
    {
        "matcher": {"id": "byRegexp", "options": "/^Solar /"},
        "properties": [{"id": "color", "value": {"fixedColor": "#FFD676", "mode": "fixed"}}],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/^Wind Onshore /"},
        "properties": [{"id": "color", "value": {"fixedColor": "#C9DBBE", "mode": "fixed"}}],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/^Wind Offshore /"},
        "properties": [{"id": "color", "value": {"fixedColor": "#97AA96", "mode": "fixed"}}],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/.* Actual$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "solid"}},
            {"id": "custom.lineWidth", "value": 2},
            {"id": "custom.fillOpacity", "value": 20},
            {"id": "custom.stacking", "value": {"group": "actual", "mode": "normal"}},
        ],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/.* Day-ahead Forecast$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
            {"id": "custom.fillOpacity", "value": 10},
            {"id": "custom.lineWidth", "value": 2},
            {"id": "custom.stacking", "value": {"group": "day_ahead", "mode": "normal"}},
        ],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/.* Intraday Forecast$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 8]}},
            {"id": "custom.fillOpacity", "value": 10},
            {"id": "custom.lineWidth", "value": 2},
            {"id": "custom.stacking", "value": {"group": "intraday", "mode": "normal"}},
        ],
    },
    {
        "matcher": {"id": "byRegexp", "options": "/.* Continuous Forecast$/"},
        "properties": [
            {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [4, 6]}},
            {"id": "custom.fillOpacity", "value": 10},
            {"id": "custom.lineWidth", "value": 2},
            {"id": "custom.stacking", "value": {"group": "continuous", "mode": "normal"}},
        ],
    },
]


def table_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    *,
    description: str | None = None,
) -> dict:
    panel = {
        "datasource": datasource(),
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "custom": {
                    "align": "auto",
                    "cellOptions": {"type": "auto"},
                    "inspect": False,
                },
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": [],
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "cellHeight": "sm",
            "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
            "showHeader": True,
            "sortBy": [],
        },
        "pluginVersion": "11.3.1",
        "targets": [base_target(raw_sql, fmt="table")],
        "title": title,
        "type": "table",
    }
    if description:
        panel["description"] = description
    return panel


def barchart_panel(
    panel_id: int,
    title: str,
    raw_sql: str,
    grid_pos: dict,
    x_field: str,
    *,
    description: str | None = None,
) -> dict:
    panel = {
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
        "targets": [base_target(raw_sql, fmt="table")],
        "title": title,
        "type": "barchart",
    }
    if description:
        panel["description"] = description
    return panel


def text_panel(panel_id: int, title: str, content: str, grid_pos: dict) -> dict:
    return {
        "fieldConfig": {"defaults": {}, "overrides": []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {"code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}, "content": content, "mode": "markdown"},
        "pluginVersion": "11.3.1",
        "title": title,
        "type": "text",
    }


def templating(
    *,
    include_neighbour: bool = True,
    include_area_type: bool = True,
    include_transfer_contract: bool = True,
) -> dict:
    variables: list[dict] = [
        {
            "current": {"text": "DE-LU", "value": "DE-LU"},
            "definition": NEGATIVE_PRICE_COUNTRY_QUERY,
            "label": "Country / Zone",
            "name": "Country",
            "options": [],
            "query": NEGATIVE_PRICE_COUNTRY_QUERY,
            "refresh": 1,
            "regex": "",
            "sort": 1,
            "type": "query",
        }
    ]
    if include_area_type:
        variables.append(
            {
                "current": {"text": "BZN", "value": "BZN"},
                "definition": NEGATIVE_PRICE_AREA_TYPE_QUERY,
                "label": "Area Type",
                "name": "Area_Type",
                "options": [],
                "query": NEGATIVE_PRICE_AREA_TYPE_QUERY,
                "refresh": 1,
                "regex": "",
                "sort": 0,
                "type": "query",
            }
        )
    if include_neighbour:
        neighbour_query = (
            'WITH connected_neighbours AS ('
            'SELECT DISTINCT x.neighbour FROM ('
            'SELECT "InAreaDisplayName" AS neighbour FROM entsoe_fms."ForecastedTransferCapacities" '
            'WHERE "OutAreaDisplayName" = \'$Country\' AND "DateTime(UTC)" >= now() - interval \'730 days\' '
            'UNION SELECT "OutAreaDisplayName" AS neighbour FROM entsoe_fms."ForecastedTransferCapacities" '
            'WHERE "InAreaDisplayName" = \'$Country\' AND "DateTime(UTC)" >= now() - interval \'730 days\''
            ') x WHERE x.neighbour <> \'$Country\') SELECT neighbour FROM connected_neighbours ORDER BY 1'
        )
        variables.append(
            {
                "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                "definition": neighbour_query,
                "includeAll": True,
                "label": "Connected Neighbour",
                "multi": True,
                "name": "Neighbour",
                "options": [],
                "query": neighbour_query,
                "refresh": 1,
                "regex": "",
                "sort": 1,
                "type": "query",
            }
        )
    if include_transfer_contract:
        variables.append(
            {
                "current": {"text": DAY_AHEAD_TRANSFER_CONTRACT, "value": DAY_AHEAD_TRANSFER_CONTRACT},
                "definition": "Day-ahead,Week-ahead,Month-ahead,Year-ahead",
                "label": "Transfer Contract",
                "name": "Transfer_Contract",
                "options": [],
                "query": "Day-ahead,Week-ahead,Month-ahead,Year-ahead",
                "refresh": 1,
                "regex": "",
                "type": "custom",
            }
        )
    return {"list": variables}


def dashboard_shell(
    *,
    title: str,
    uid: str,
    description: str,
    tags: list[str],
    panels: list[dict],
    time_from: str,
    time_to: str,
    refresh: str = "5m",
    include_transfer_contract: bool = True,
) -> dict:
    return {
        "__inputs": [],
        "__requires": [
            {"type": "datasource", "id": "grafana-postgresql-datasource", "name": "OPENDATA", "version": "1.0.0"},
            {"type": "panel", "id": "stat", "name": "Stat", "version": "11.3.1"},
            {"type": "panel", "id": "timeseries", "name": "Time series", "version": "11.3.1"},
            {"type": "panel", "id": "table", "name": "Table", "version": "11.3.1"},
            {"type": "panel", "id": "barchart", "name": "Bar chart", "version": "11.3.1"},
            {"type": "panel", "id": "text", "name": "Text", "version": "11.3.1"},
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
        "description": description,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "liveNow": False,
        "panels": panels,
        "refresh": refresh,
        "schemaVersion": 40,
        "style": "light",
        "tags": tags,
        "templating": templating(include_transfer_contract=include_transfer_contract),
        "time": {"from": time_from, "to": time_to},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


def da_hourly_price_where() -> str:
    return (
        '"AreaDisplayName" = \'$Country\' '
        'AND "AreaTypeCode" = \'BZN\' '
        f'AND {da_sequence_where()}'
    )


def da_sequence_where() -> str:
    return '(TRIM(COALESCE("Sequence", \'\')) = \'\' OR "Sequence" = \'1\')'


def da_hourly_prices_cte(name: str = "prices", *, country: str = "'$Country'") -> str:
    return (
        f'{name} AS (\n'
        '    SELECT date_bin(INTERVAL \'15 minutes\', "DateTime(UTC)", TIMESTAMP \'1970-01-01\') AS ts, AVG("Price[Currency/MWh]") AS price_mwh\n'
        '    FROM entsoe_fms."EnergyPrices"\n'
        f'    WHERE "AreaDisplayName" = {country}\n'
        "      AND \"AreaTypeCode\" = 'BZN'\n"
        f'      AND {da_sequence_where()}\n'
        f'      AND {time_filter()}\n'
        '    GROUP BY 1\n'
        ')'
    )


def da_hourly_area_prices_cte(
    name: str = "neighbour_prices",
    *,
    area_alias: str = "neighbour",
    area_filter: str = '"AreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)',
) -> str:
    return (
        f'{name} AS (\n'
        f'    SELECT date_bin(INTERVAL \'15 minutes\', "DateTime(UTC)", TIMESTAMP \'1970-01-01\') AS ts, "AreaDisplayName" AS {area_alias}, AVG("Price[Currency/MWh]") AS price_mwh\n'
        '    FROM entsoe_fms."EnergyPrices"\n'
        f'    WHERE {area_filter}\n'
        "      AND \"AreaTypeCode\" = 'BZN'\n"
        f'      AND {da_sequence_where()}\n'
        f'      AND {time_filter()}\n'
        '    GROUP BY 1, 2\n'
        ')'
    )


def time_filter(column: str = '"DateTime(UTC)"') -> str:
    return f"{column} >= to_timestamp($__from / 1000.0) AND {column} <= to_timestamp($__to / 1000.0)"


def price_category_case() -> str:
    return (
        "CASE "
        "WHEN TRIM(COALESCE(\"Sequence\", '')) = '' OR \"Sequence\" = '1' THEN 'Day-ahead 12:00 auction (EPEX SPOT)' "
        "WHEN \"Sequence\" = '2' THEN 'Day-ahead 10:15 auction (EXAA)' "
        "WHEN \"Sequence\" = '3' AND TRIM(COALESCE(\"ContractType\", '')) <> '' THEN 'Intraday (' || TRIM(\"ContractType\") || ')' "
        "WHEN \"Sequence\" = '3' THEN 'Intraday (ENTSO-E source)' "
        "ELSE COALESCE(NULLIF(TRIM(\"ContractType\"), ''), 'Sequence ' || COALESCE(NULLIF(\"Sequence\", ''), 'unknown')) END"
    )


def hour_bucket(column: str = '"DateTime(UTC)"') -> str:
    return f"date_bin(INTERVAL '15 minutes', {column}, TIMESTAMP '1970-01-01')"


def quarter_hour_hours_expr(count_expr: str = "COUNT(*)") -> str:
    return f"(({count_expr}) * 0.25)"


def local_day_expr(column: str) -> str:
    return f"(({column} AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Berlin')::date"


def resolution_hours_expr(alias: str = "g") -> str:
    return (
        f"CASE "
        f"WHEN {alias}.\"ResolutionCode\" IN ('PT15M', 'P15M') THEN 0.25 "
        f"WHEN {alias}.\"ResolutionCode\" IN ('PT30M', 'P30M') THEN 0.5 "
        f"ELSE 1.0 END"
    )


SQL_EVENT_MIN_PRICE = f"""
WITH {da_hourly_prices_cte()}
SELECT now() AS "time", MIN(price_mwh) AS "value"
FROM prices
""".strip()


SQL_EVENT_NEG_COUNT = f"""
WITH {da_hourly_prices_cte()}
SELECT now() AS "time", {quarter_hour_hours_expr("COUNT(*) FILTER (WHERE price_mwh < 0)")} AS "value"
FROM prices
""".strip()


SQL_EVENT_NEG_COUNT_SUNDAY = f"""
WITH {da_hourly_prices_cte()},
prices_with_day AS (
    SELECT ts, price_mwh, {local_day_expr("ts")} AS local_day
    FROM prices
)
SELECT now() AS "time", {quarter_hour_hours_expr("COUNT(*) FILTER (WHERE price_mwh < 0 AND local_day = " + EVENT_SUNDAY + ")")} AS "value"
FROM prices_with_day
""".strip()


SQL_EVENT_AVG_NEG = f"""
WITH {da_hourly_prices_cte()}
SELECT now() AS "time", AVG(price_mwh) FILTER (WHERE price_mwh < 0) AS "value"
FROM prices
""".strip()


SQL_EVENT_LONGEST_BLOCK = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
),
islands AS (
    SELECT ts, ts - ROW_NUMBER() OVER (ORDER BY ts) * interval '15 minutes' AS grp
    FROM negative_prices
),
blocks AS (
    SELECT COUNT(*) AS interval_count
    FROM islands
    GROUP BY grp
)
SELECT now() AS "time", COALESCE(MAX(interval_count), 0) * 0.25 AS "value"
FROM blocks
""".strip()


SQL_EVENT_LOAD_NEG = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
),
load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
)
SELECT now() AS "time", COALESCE(SUM(l.load_mw * 0.25), 0) AS "value"
FROM negative_prices p
LEFT JOIN load_ts l ON l.ts = p.ts
""".strip()


SQL_EVENT_LOAD_NEG_SUNDAY = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
      AND {local_day_expr("ts")} = {EVENT_SUNDAY}
),
load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
)
SELECT now() AS "time", COALESCE(SUM(l.load_mw * 0.25), 0) AS "value"
FROM negative_prices p
LEFT JOIN load_ts l ON l.ts = p.ts
""".strip()


SQL_PRICE_COMPARISON = f"""
WITH entsoe_prices AS (
    SELECT
        "DateTime(UTC)" AS ts,
        {price_category_case()} AS metric,
        "Price[Currency/MWh]" AS value
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = 'BZN'
      AND {time_filter()}
),
epex_intraday_prices AS (
    SELECT
        delivery_start_utc AS ts,
        'EPEX Intraday Auction ' || auction_name AS metric,
        AVG(value) AS value
    FROM epex_spot.intraday_auction_prices_volumes
    WHERE market_area = '$Country'
      AND metric = 'price'
      AND {time_filter("delivery_start_utc")}
    GROUP BY 1, 2
),
prices AS (
    SELECT * FROM entsoe_prices
    UNION ALL
    SELECT * FROM epex_intraday_prices
)
SELECT ts AS "time", metric, value AS "value"
FROM prices
ORDER BY 1, 2
""".strip()


SQL_PRICE_PRODUCT_AVAILABILITY = f"""
SELECT
    source,
    price_product,
    COUNT(*) AS intervals,
    MIN(ts) AS first_timestamp_utc,
    MAX(ts) AS last_timestamp_utc,
    ROUND(MIN(price_mwh)::numeric, 2) AS min_price_eur_mwh,
    ROUND(AVG(price_mwh)::numeric, 2) AS avg_price_eur_mwh,
    ROUND(MAX(price_mwh)::numeric, 2) AS max_price_eur_mwh
FROM (
    SELECT
        'ENTSO-E' AS source,
        {price_category_case()} AS price_product,
        "DateTime(UTC)" AS ts,
        "Price[Currency/MWh]" AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = 'BZN'
      AND {time_filter()}

    UNION ALL

    SELECT
        'EPEX' AS source,
        'Intraday Auction ' || auction_name AS price_product,
        delivery_start_utc AS ts,
        value AS price_mwh
    FROM epex_spot.intraday_auction_prices_volumes
    WHERE market_area = '$Country'
      AND metric = 'price'
      AND {time_filter("delivery_start_utc")}
) prices
GROUP BY 1, 2
ORDER BY source, intervals DESC, price_product
""".strip()


SQL_EVENT_DAILY_COMPARISON = f"""
WITH quarter_hour_prices AS (
    SELECT
        {hour_bucket()} AS ts,
        AVG("Price[Currency/MWh]") AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE {da_hourly_price_where()}
      AND {time_filter()}
    GROUP BY 1
),
prices AS (
    SELECT
        ts,
        {local_day_expr('ts')} AS local_day,
        price_mwh
    FROM quarter_hour_prices
),
load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(wind_solar_mw) AS wind_solar_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(CASE WHEN "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore') THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_solar_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
),
flow_ts AS (
    SELECT
        ts,
        AVG(export_mw) - AVG(import_mw) AS net_export_delta_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(import_mw) AS import_mw,
            SUM(export_mw) AS export_mw
        FROM (
            SELECT "DateTime(UTC)", "Flow[MW]" AS import_mw, 0::double precision AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "InAreaDisplayName" = '$Country'
              AND {time_filter()}
            UNION ALL
            SELECT "DateTime(UTC)", 0::double precision AS import_mw, "Flow[MW]" AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "OutAreaDisplayName" = '$Country'
              AND {time_filter()}
        ) interval_flows
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
),
joined AS (
    SELECT
        p.local_day,
        p.ts,
        p.price_mwh,
        l.load_mw,
        g.wind_solar_mw,
        l.load_mw - COALESCE(g.wind_solar_mw, 0) AS residual_load_mw,
        f.net_export_delta_mw
    FROM prices p
    LEFT JOIN load_ts l ON l.ts = p.ts
    LEFT JOIN generation_ts g ON g.ts = p.ts
    LEFT JOIN flow_ts f ON f.ts = p.ts
)
SELECT
    local_day,
    TO_CHAR(local_day, 'Dy') AS weekday,
    ROUND({quarter_hour_hours_expr()}::numeric, 2) AS day_ahead_hours,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE price_mwh < 0)")}::numeric, 2) AS negative_hours,
    ROUND(MIN(price_mwh)::numeric, 2) AS min_price_eur_mwh,
    ROUND(AVG(price_mwh)::numeric, 2) AS avg_price_eur_mwh,
    ROUND(AVG(load_mw)::numeric, 1) AS avg_load_mw,
    ROUND(AVG(wind_solar_mw)::numeric, 1) AS avg_wind_solar_mw,
    ROUND(AVG(residual_load_mw)::numeric, 1) AS avg_residual_load_mw,
    ROUND(AVG(net_export_delta_mw)::numeric, 1) AS avg_net_export_delta_mw
FROM joined
GROUP BY 1
ORDER BY 1
""".strip()


SQL_DEMAND_WIND_SOLAR_RESIDUAL = f"""
WITH load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(solar_mw) AS solar_mw,
        AVG(wind_onshore_mw) AS wind_onshore_mw,
        AVG(wind_offshore_mw) AS wind_offshore_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Onshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_onshore_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Offshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_offshore_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, "DateTime(UTC)"
    ) quarter_hourly
    GROUP BY 1
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT l.ts, 'Total Load' AS metric, l.load_mw AS value
    FROM load_ts l
    UNION ALL
    SELECT g.ts, 'Solar' AS metric, g.solar_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Onshore' AS metric, g.wind_onshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Offshore' AS metric, g.wind_offshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT l.ts, 'Residual Load' AS metric, l.load_mw - COALESCE(g.solar_mw, 0) - COALESCE(g.wind_onshore_mw, 0) - COALESCE(g.wind_offshore_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
) s
ORDER BY 1, 2
""".strip()


SQL_DEMAND_WIND_SOLAR_STACKED = f"""
WITH load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(solar_mw) AS solar_mw,
        AVG(wind_onshore_mw) AS wind_onshore_mw,
        AVG(wind_offshore_mw) AS wind_offshore_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Onshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_onshore_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Offshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_offshore_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, "DateTime(UTC)"
    ) quarter_hourly
    GROUP BY 1
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT l.ts, 'Residual Load' AS metric, GREATEST(l.load_mw - COALESCE(g.solar_mw, 0) - COALESCE(g.wind_onshore_mw, 0) - COALESCE(g.wind_offshore_mw, 0), 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    UNION ALL
    SELECT g.ts, 'Solar' AS metric, g.solar_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Onshore' AS metric, g.wind_onshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Offshore' AS metric, g.wind_offshore_mw AS value
    FROM generation_ts g
) s
ORDER BY 1, 2
""".strip()


SQL_DEMAND_WIND_SOLAR_RESIDUAL_TRADE = f"""
WITH load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(solar_mw) AS solar_mw,
        AVG(wind_onshore_mw) AS wind_onshore_mw,
        AVG(wind_offshore_mw) AS wind_offshore_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Onshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_onshore_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Offshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_offshore_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, "DateTime(UTC)"
    ) quarter_hourly
    GROUP BY 1
),
flow_ts AS (
    SELECT
        ts,
        AVG(import_mw) AS import_mw,
        AVG(export_mw) AS export_mw,
        AVG(export_mw) - AVG(import_mw) AS net_export_delta_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(import_mw) AS import_mw,
            SUM(export_mw) AS export_mw
        FROM (
            SELECT "DateTime(UTC)", "Flow[MW]" AS import_mw, 0::double precision AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "InAreaDisplayName" = '$Country'
              AND {time_filter()}
            UNION ALL
            SELECT "DateTime(UTC)", 0::double precision AS import_mw, "Flow[MW]" AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "OutAreaDisplayName" = '$Country'
              AND {time_filter()}
        ) interval_flows
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT l.ts, 'Total Load' AS metric, l.load_mw AS value
    FROM load_ts l
    UNION ALL
    SELECT g.ts, 'Solar' AS metric, g.solar_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Onshore' AS metric, g.wind_onshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Offshore' AS metric, g.wind_offshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT l.ts, 'Imports' AS metric, COALESCE(f.import_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN flow_ts f ON f.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Exports' AS metric, COALESCE(f.export_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN flow_ts f ON f.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Net Export Delta' AS metric, COALESCE(f.net_export_delta_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN flow_ts f ON f.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Residual Load' AS metric, l.load_mw - COALESCE(g.solar_mw, 0) - COALESCE(g.wind_onshore_mw, 0) - COALESCE(g.wind_offshore_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    UNION ALL
    SELECT l.ts, 'Residual Load incl. Trade' AS metric, l.load_mw - COALESCE(g.solar_mw, 0) - COALESCE(g.wind_onshore_mw, 0) - COALESCE(g.wind_offshore_mw, 0) + COALESCE(f.net_export_delta_mw, 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    LEFT JOIN flow_ts f ON f.ts = l.ts
) s
ORDER BY 1, 2
""".strip()


SQL_DEMAND_WIND_SOLAR_TRADE_STACKED = f"""
WITH load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(solar_mw) AS solar_mw,
        AVG(wind_onshore_mw) AS wind_onshore_mw,
        AVG(wind_offshore_mw) AS wind_offshore_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Onshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_onshore_mw,
            SUM(CASE WHEN "ProductionType" = 'Wind Offshore' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_offshore_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, "DateTime(UTC)"
    ) quarter_hourly
    GROUP BY 1
),
flow_ts AS (
    SELECT
        ts,
        AVG(export_mw) - AVG(import_mw) AS net_export_delta_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(import_mw) AS import_mw,
            SUM(export_mw) AS export_mw
        FROM (
            SELECT "DateTime(UTC)", "Flow[MW]" AS import_mw, 0::double precision AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "InAreaDisplayName" = '$Country'
              AND {time_filter()}
            UNION ALL
            SELECT "DateTime(UTC)", 0::double precision AS import_mw, "Flow[MW]" AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "OutAreaDisplayName" = '$Country'
              AND {time_filter()}
        ) interval_flows
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT l.ts, 'Residual Load incl. Trade' AS metric, GREATEST(l.load_mw - COALESCE(g.solar_mw, 0) - COALESCE(g.wind_onshore_mw, 0) - COALESCE(g.wind_offshore_mw, 0) + COALESCE(f.net_export_delta_mw, 0), 0) AS value
    FROM load_ts l
    LEFT JOIN generation_ts g ON g.ts = l.ts
    LEFT JOIN flow_ts f ON f.ts = l.ts
    UNION ALL
    SELECT g.ts, 'Solar' AS metric, g.solar_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Onshore' AS metric, g.wind_onshore_mw AS value
    FROM generation_ts g
    UNION ALL
    SELECT g.ts, 'Wind Offshore' AS metric, g.wind_offshore_mw AS value
    FROM generation_ts g
) s
ORDER BY 1, 2
""".strip()


SQL_GENERATION_MIX = f"""
SELECT ts AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT {hour_bucket()} AS ts, "ProductionType" AS metric, AVG("ActualGenerationOutput[MW]") AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE {time_filter()}
      AND "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
    GROUP BY 1, 2
) s
GROUP BY 1, 2
ORDER BY 1
""".strip()


SQL_STORAGE_RESPONSE = f"""
SELECT ts AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT
        {hour_bucket()} AS ts,
        CASE
            WHEN "ProductionType" = 'Hydro Pumped Storage' THEN 'Pumped Storage Discharge'
            WHEN "ProductionType" ILIKE '%Battery%' THEN 'Battery Discharge'
        END AS metric,
        AVG("ActualGenerationOutput[MW]") AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND ("ProductionType" = 'Hydro Pumped Storage' OR "ProductionType" ILIKE '%Battery%')
      AND {time_filter()}
    GROUP BY 1, 2
    UNION ALL
    SELECT
        {hour_bucket()} AS ts,
        CASE
            WHEN "ProductionType" = 'Hydro Pumped Storage' THEN 'Pumped Storage Charge'
            WHEN "ProductionType" ILIKE '%Battery%' THEN 'Battery Charge'
        END AS metric,
        -1 * AVG(CASE WHEN "ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE "ActualConsumption[MW]" END) AS value
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND ("ProductionType" = 'Hydro Pumped Storage' OR "ProductionType" ILIKE '%Battery%')
      AND {time_filter()}
    GROUP BY 1, 2
) s
WHERE metric IS NOT NULL AND value IS NOT NULL
GROUP BY 1, 2
ORDER BY 1
""".strip()


SQL_FORECAST_BY_TECHNOLOGY = f"""
WITH actual AS (
    SELECT
        {hour_bucket()} AS ts,
        "ProductionType" AS production_type,
        AVG("ActualGenerationOutput[MW]") AS actual_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1, 2
),
forecast AS (
    SELECT
        {hour_bucket()} AS ts,
        "ProductionType" AS production_type,
        AVG("DayAheadGenerationForecast[MW]") AS day_ahead_mw,
        AVG("IntradayGenerationForecast[MW]") AS intraday_mw,
        AVG("CurrentGenerationForecast[MW]") AS current_mw
    FROM entsoe_fms."GenerationForecastsForWindAndSolar"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1, 2
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT a.ts, a.production_type || ' Actual' AS metric, a.actual_mw AS value FROM actual a
    UNION ALL SELECT f.ts, f.production_type || ' Day-ahead Forecast' AS metric, f.day_ahead_mw AS value FROM forecast f
    UNION ALL SELECT f.ts, f.production_type || ' Intraday Forecast' AS metric, f.intraday_mw AS value FROM forecast f
    UNION ALL SELECT f.ts, f.production_type || ' Continuous Forecast' AS metric, f.current_mw AS value FROM forecast f
) s
ORDER BY 1, 2
""".strip()


SQL_CROSS_BORDER_FLOWS = f"""
WITH aggregated_flows AS (
    SELECT
        ts,
        AVG(import_mw) AS import_mw,
        AVG(export_mw) AS export_mw,
        AVG(import_mw) - AVG(export_mw) AS net_position_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(import_mw) AS import_mw,
            SUM(export_mw) AS export_mw
        FROM (
            SELECT "DateTime(UTC)", "Flow[MW]" AS import_mw, 0::double precision AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "InAreaDisplayName" = '$Country'
              AND {time_filter()}
            UNION ALL
            SELECT "DateTime(UTC)", 0::double precision AS import_mw, "Flow[MW]" AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "OutAreaDisplayName" = '$Country'
              AND {time_filter()}
        ) interval_flows
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
),
flows AS (
    SELECT ts, 'Imports' AS metric, import_mw AS value FROM aggregated_flows
    UNION ALL
    SELECT ts, 'Exports' AS metric, -1 * export_mw AS value FROM aggregated_flows
    UNION ALL
    SELECT ts, 'Net Position' AS metric, net_position_mw AS value FROM aggregated_flows
)
SELECT ts AS "time", metric, AVG(value) AS "value"
FROM flows
GROUP BY 1, 2
ORDER BY 1
""".strip()


SQL_CROSS_BORDER_NET_POSITIONS = f"""
WITH home_country AS (
    SELECT
        CASE
            WHEN '$Country' = 'DE-LU' THEN 'DE'
            WHEN '$Country' IN ('United Kingdom (UK)', 'UK') THEN 'GB'
            WHEN '$Country' ~ '^[A-Z]{{2}}([-(].*)?$' THEN substring('$Country' from '^([A-Z]{{2}})')
            WHEN '$Country' ~ '\\(([A-Z]{{2}})\\)$' THEN substring('$Country' from '\\(([A-Z]{{2}})\\)$')
            ELSE '$Country'
        END AS home_country_code
),
imports AS (
    SELECT
        {hour_bucket()} AS ts,
        CASE
            WHEN "OutAreaDisplayName" = 'DE-LU' THEN 'DE'
            WHEN "OutAreaDisplayName" IN ('United Kingdom (UK)', 'UK') THEN 'GB'
            WHEN "OutAreaDisplayName" ~ '^[A-Z]{{2}}([-(].*)?$' THEN substring("OutAreaDisplayName" from '^([A-Z]{{2}})')
            WHEN "OutAreaDisplayName" ~ '\\(([A-Z]{{2}})\\)$' THEN substring("OutAreaDisplayName" from '\\(([A-Z]{{2}})\\)$')
            ELSE "OutAreaDisplayName"
        END AS neighbour_country,
        AVG("Flow[MW]") AS net_position_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "InAreaDisplayName" = '$Country'
      AND {time_filter()}
    GROUP BY 1, 2
),
exports AS (
    SELECT
        {hour_bucket()} AS ts,
        CASE
            WHEN "InAreaDisplayName" = 'DE-LU' THEN 'DE'
            WHEN "InAreaDisplayName" IN ('United Kingdom (UK)', 'UK') THEN 'GB'
            WHEN "InAreaDisplayName" ~ '^[A-Z]{{2}}([-(].*)?$' THEN substring("InAreaDisplayName" from '^([A-Z]{{2}})')
            WHEN "InAreaDisplayName" ~ '\\(([A-Z]{{2}})\\)$' THEN substring("InAreaDisplayName" from '\\(([A-Z]{{2}})\\)$')
            ELSE "InAreaDisplayName"
        END AS neighbour_country,
        -1 * AVG("Flow[MW]") AS net_position_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "OutAreaDisplayName" = '$Country'
      AND {time_filter()}
    GROUP BY 1, 2
),
positions AS (
    SELECT * FROM imports
    UNION ALL
    SELECT * FROM exports
),
filtered_positions AS (
    SELECT p.ts, p.neighbour_country, p.net_position_mw
    FROM positions p
    CROSS JOIN home_country h
    WHERE p.neighbour_country IS NOT NULL
      AND p.neighbour_country <> h.home_country_code
)
SELECT ts AS "time", neighbour_country AS metric, SUM(net_position_mw) AS "value"
FROM filtered_positions
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


SQL_NEIGHBOUR_PRICE_COMPARISON = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
home_prices AS (
    SELECT ts, '$Country' AS metric, price_mwh
    FROM (
        SELECT {hour_bucket()} AS ts, AVG("Price[Currency/MWh]") AS price_mwh
        FROM entsoe_fms."EnergyPrices"
        WHERE {da_hourly_price_where()}
          AND {time_filter()}
        GROUP BY 1
    ) h
),
neighbour_prices AS (
    SELECT {hour_bucket()} AS ts, "AreaDisplayName" AS metric, AVG("Price[Currency/MWh]") AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND "AreaTypeCode" = 'BZN'
      AND {da_sequence_where()}
      AND {time_filter()}
    GROUP BY 1, 2
),
prices AS (
    SELECT * FROM home_prices
    UNION ALL
    SELECT * FROM neighbour_prices
)
SELECT ts AS "time", metric, AVG(price_mwh) AS "value"
FROM prices
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


SQL_NEIGHBOUR_PRICE_SPREAD_EVENT = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
{da_hourly_prices_cte("home_prices")},
{da_hourly_area_prices_cte()},
paired AS (
    SELECT
        h.ts,
        n.neighbour,
        h.price_mwh AS home_price,
        n.price_mwh AS neighbour_price,
        h.price_mwh - n.price_mwh AS spread_eur_mwh
    FROM home_prices h
    JOIN neighbour_prices n ON n.ts = h.ts
)
SELECT
    neighbour,
    ROUND({quarter_hour_hours_expr()}::numeric, 2) AS matched_price_hours,
    ROUND(AVG(home_price)::numeric, 2) AS avg_home_price_eur_mwh,
    ROUND(AVG(neighbour_price)::numeric, 2) AS avg_neighbour_price_eur_mwh,
    ROUND(MIN(neighbour_price)::numeric, 2) AS min_neighbour_price_eur_mwh,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE neighbour_price < 0)")}::numeric, 2) AS neighbour_negative_hours,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE home_price < 0 AND neighbour_price < 0)")}::numeric, 2) AS simultaneous_negative_hours,
    ROUND(AVG(spread_eur_mwh)::numeric, 2) AS avg_home_minus_neighbour_eur_mwh,
    ROUND(MIN(spread_eur_mwh)::numeric, 2) AS min_home_minus_neighbour_eur_mwh,
    ROUND(MAX(spread_eur_mwh)::numeric, 2) AS max_home_minus_neighbour_eur_mwh
FROM paired
GROUP BY 1
ORDER BY simultaneous_negative_hours DESC, avg_home_minus_neighbour_eur_mwh ASC, neighbour
""".strip()


SQL_BORDER_CAPACITY_TABLE = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
capacities AS (
    SELECT "DateTime(UTC)" AS ts, 'Import'::text AS direction, "OutAreaDisplayName" AS neighbour, "ForecastTransferCapacity[MW]" AS capacity_mw
    FROM entsoe_fms."ForecastedTransferCapacities"
    WHERE "InAreaDisplayName" = '$Country'
      AND "OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND "ContractType" = 'Day-ahead'
      AND {time_filter()}
    UNION ALL
    SELECT "DateTime(UTC)" AS ts, 'Export'::text AS direction, "InAreaDisplayName" AS neighbour, "ForecastTransferCapacity[MW]" AS capacity_mw
    FROM entsoe_fms."ForecastedTransferCapacities"
    WHERE "OutAreaDisplayName" = '$Country'
      AND "InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND "ContractType" = 'Day-ahead'
      AND {time_filter()}
),
flows AS (
    SELECT "DateTime(UTC)" AS ts, 'Import'::text AS direction, "OutAreaDisplayName" AS neighbour, "Flow[MW]" AS flow_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "InAreaDisplayName" = '$Country'
      AND "OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND {time_filter()}
    UNION ALL
    SELECT "DateTime(UTC)" AS ts, 'Export'::text AS direction, "InAreaDisplayName" AS neighbour, "Flow[MW]" AS flow_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "OutAreaDisplayName" = '$Country'
      AND "InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND {time_filter()}
),
{da_hourly_prices_cte("home_prices")},
{da_hourly_area_prices_cte()},
spreads AS (
    SELECT h.ts, n.neighbour, h.price_mwh - n.price_mwh AS spread_eur_mwh
    FROM home_prices h
    JOIN neighbour_prices n ON n.ts = h.ts
)
SELECT
    c.direction,
    c.neighbour,
    ROUND(AVG(c.capacity_mw)::numeric, 1) AS avg_capacity_mw,
    ROUND(MIN(c.capacity_mw)::numeric, 1) AS min_capacity_mw,
    ROUND(AVG(f.flow_mw)::numeric, 1) AS avg_physical_flow_mw,
    ROUND(AVG(s.spread_eur_mwh)::numeric, 2) AS avg_home_minus_neighbour_eur_mwh
FROM capacities c
LEFT JOIN flows f ON f.direction = c.direction AND f.neighbour = c.neighbour AND f.ts = c.ts
LEFT JOIN spreads s ON s.neighbour = c.neighbour AND s.ts = c.ts
GROUP BY 1, 2
ORDER BY direction, avg_capacity_mw DESC
""".strip()


SQL_CROSS_BORDER_WEEKEND_DELTA = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
flows AS (
    SELECT
        {local_day_expr('"DateTime(UTC)"')} AS local_day,
        "OutAreaDisplayName" AS neighbour,
        AVG("Flow[MW]") AS import_mw,
        0::double precision AS export_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "InAreaDisplayName" = '$Country'
      AND "OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND {time_filter()}
    GROUP BY 1, 2
    UNION ALL
    SELECT
        {local_day_expr('"DateTime(UTC)"')} AS local_day,
        "InAreaDisplayName" AS neighbour,
        0::double precision AS import_mw,
        AVG("Flow[MW]") AS export_mw
    FROM entsoe_fms."PhysicalFlows"
    WHERE "OutAreaDisplayName" = '$Country'
      AND "InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
      AND {time_filter()}
    GROUP BY 1, 2
),
daily AS (
    SELECT
        local_day,
        neighbour,
        SUM(import_mw) AS import_mw,
        SUM(export_mw) AS export_mw,
        SUM(export_mw) - SUM(import_mw) AS net_export_delta_mw
    FROM flows
    GROUP BY 1, 2
),
pivoted AS (
    SELECT
        neighbour,
        AVG(import_mw) FILTER (WHERE local_day = DATE '2026-04-25') AS saturday_import_mw,
        AVG(import_mw) FILTER (WHERE local_day = DATE '2026-04-26') AS sunday_import_mw,
        AVG(export_mw) FILTER (WHERE local_day = DATE '2026-04-25') AS saturday_export_mw,
        AVG(export_mw) FILTER (WHERE local_day = DATE '2026-04-26') AS sunday_export_mw,
        AVG(net_export_delta_mw) FILTER (WHERE local_day = DATE '2026-04-25') AS saturday_net_export_delta_mw,
        AVG(net_export_delta_mw) FILTER (WHERE local_day = DATE '2026-04-26') AS sunday_net_export_delta_mw
    FROM daily
    GROUP BY 1
)
SELECT
    neighbour,
    ROUND(saturday_import_mw::numeric, 1) AS saturday_import_mw,
    ROUND(sunday_import_mw::numeric, 1) AS sunday_import_mw,
    ROUND((sunday_import_mw - saturday_import_mw)::numeric, 1) AS import_delta_sun_minus_sat_mw,
    ROUND(saturday_export_mw::numeric, 1) AS saturday_export_mw,
    ROUND(sunday_export_mw::numeric, 1) AS sunday_export_mw,
    ROUND((sunday_export_mw - saturday_export_mw)::numeric, 1) AS export_delta_sun_minus_sat_mw,
    ROUND(saturday_net_export_delta_mw::numeric, 1) AS saturday_net_export_delta_mw,
    ROUND(sunday_net_export_delta_mw::numeric, 1) AS sunday_net_export_delta_mw,
    ROUND((sunday_net_export_delta_mw - saturday_net_export_delta_mw)::numeric, 1) AS net_delta_sun_minus_sat_mw
FROM pivoted
ORDER BY ABS(sunday_net_export_delta_mw - saturday_net_export_delta_mw) DESC NULLS LAST, neighbour
""".strip()


SQL_CROSS_BORDER_CAPACITY_UTILISATION = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
capacity_ts AS (
    SELECT
        {hour_bucket()} AS ts,
        SUM(import_capacity_mw) AS import_capacity_mw,
        SUM(export_capacity_mw) AS export_capacity_mw
    FROM (
        SELECT "DateTime(UTC)", "ForecastTransferCapacity[MW]" AS import_capacity_mw, 0::double precision AS export_capacity_mw
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
          AND "ContractType" = 'Day-ahead'
          AND {time_filter()}
        UNION ALL
        SELECT "DateTime(UTC)", 0::double precision AS import_capacity_mw, "ForecastTransferCapacity[MW]" AS export_capacity_mw
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
          AND "ContractType" = 'Day-ahead'
          AND {time_filter()}
    ) capacities
    GROUP BY 1
),
flow_ts AS (
    SELECT
        {hour_bucket()} AS ts,
        SUM(import_mw) AS import_mw,
        SUM(export_mw) AS export_mw
    FROM (
        SELECT "DateTime(UTC)", "Flow[MW]" AS import_mw, 0::double precision AS export_mw
        FROM entsoe_fms."PhysicalFlows"
        WHERE "InAreaDisplayName" = '$Country'
          AND {time_filter()}
        UNION ALL
        SELECT "DateTime(UTC)", 0::double precision AS import_mw, "Flow[MW]" AS export_mw
        FROM entsoe_fms."PhysicalFlows"
        WHERE "OutAreaDisplayName" = '$Country'
          AND {time_filter()}
    ) flows
    GROUP BY 1
)
SELECT ts AS "time", metric, value AS "value"
FROM (
    SELECT c.ts, 'Import Utilisation' AS metric, 100.0 * COALESCE(f.import_mw, 0) / NULLIF(c.import_capacity_mw, 0) AS value
    FROM capacity_ts c
    LEFT JOIN flow_ts f ON f.ts = c.ts
    UNION ALL
    SELECT c.ts, 'Export Utilisation' AS metric, 100.0 * COALESCE(f.export_mw, 0) / NULLIF(c.export_capacity_mw, 0) AS value
    FROM capacity_ts c
    LEFT JOIN flow_ts f ON f.ts = c.ts
) utilisation
WHERE value IS NOT NULL
ORDER BY 1, 2
""".strip()


SQL_UNAVAILABILITY_NEGATIVE = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
)
SELECT
    u."ProductionType" AS production_type,
    COALESCE(u."ReasonText", u."Reason", 'Unknown') AS reason,
    COUNT(DISTINCT u."InstanceCode") AS affected_assets,
    ROUND(AVG(u."AvailableCapacity[MW]")::numeric, 1) AS avg_available_capacity_mw,
    MIN(u."StartOutage(UTC)") AS first_outage_start,
    MAX(u."EndOutage(UTC)") AS last_outage_end
FROM entsoe_fms."UnavailabilityOfProductionAndGenerationUnits" u
JOIN negative_prices p
  ON p.ts >= u."StartTimeSeries(UTC)"
 AND p.ts < u."EndTimeSeries(UTC)"
WHERE u."AreaDisplayName" = '$Country'
  AND (u."AreaTypeCode" = '$Area_Type' OR u."AreaTypeCode" = 'BZN')
GROUP BY 1, 2
ORDER BY affected_assets DESC, avg_available_capacity_mw DESC NULLS LAST
LIMIT 25
""".strip()


SQL_REVENUE_PROXY_EVENT = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts, price_mwh
    FROM prices
    WHERE price_mwh < 0
),
generation AS (
    SELECT
        {hour_bucket('g."DateTime(UTC)"')} AS ts,
        g."ResolutionCode",
        g."ProductionType" AS production_type,
        AVG(g."ActualGenerationOutput[MW]") AS generation_mw
    FROM entsoe_fms."AggregatedGenerationPerType" g
    WHERE g."AreaDisplayName" = '$Country'
      AND g."AreaTypeCode" = '$Area_Type'
      AND {time_filter('g."DateTime(UTC)"')}
    GROUP BY 1, 2, 3
),
joined AS (
    SELECT
        p.ts AS price_ts,
        p.price_mwh,
        g.production_type,
        g.generation_mw,
        {resolution_hours_expr()} AS duration_h
    FROM negative_prices p
    JOIN generation g
      ON g.ts = p.ts
)
SELECT
    production_type,
    ROUND(SUM(generation_mw * duration_h)::numeric, 1) AS generation_at_negative_prices_mwh,
    ROUND(AVG(price_mwh)::numeric, 2) AS avg_negative_price_eur_mwh,
    ROUND(SUM(generation_mw * duration_h * price_mwh)::numeric, 0) AS revenue_proxy_eur
FROM joined
GROUP BY 1
HAVING SUM(generation_mw * duration_h) > 0
ORDER BY revenue_proxy_eur ASC
LIMIT 20
""".strip()


SQL_EVENT_CONTEXT_TABLE = f"""
WITH {da_hourly_prices_cte()},
load_ts AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
generation_ts AS (
    SELECT
        ts,
        AVG(solar_mw) AS solar_mw,
        AVG(wind_mw) AS wind_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
            SUM(CASE WHEN "ProductionType" IN ('Wind Onshore', 'Wind Offshore') THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
          AND {time_filter()}
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
),
storage_ts AS (
    SELECT
        ts,
        AVG(ps_discharge_mw) AS ps_discharge_mw,
        AVG(ps_charge_mw) AS ps_charge_mw,
        AVG(battery_discharge_mw) AS battery_discharge_mw,
        AVG(battery_charge_mw) AS battery_charge_mw
    FROM (
        SELECT
            {hour_bucket()} AS ts,
            "DateTime(UTC)" AS source_ts,
            SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS ps_discharge_mw,
            SUM(CASE WHEN "ProductionType" = 'Hydro Pumped Storage' THEN COALESCE(CASE WHEN "ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE "ActualConsumption[MW]" END, 0) ELSE 0 END) AS ps_charge_mw,
            SUM(CASE WHEN "ProductionType" ILIKE '%Battery%' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS battery_discharge_mw,
            SUM(CASE WHEN "ProductionType" ILIKE '%Battery%' THEN COALESCE(CASE WHEN "ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE "ActualConsumption[MW]" END, 0) ELSE 0 END) AS battery_charge_mw
        FROM entsoe_fms."AggregatedGenerationPerType"
        WHERE "AreaDisplayName" = '$Country'
          AND "AreaTypeCode" = '$Area_Type'
          AND ("ProductionType" = 'Hydro Pumped Storage' OR "ProductionType" ILIKE '%Battery%')
          AND {time_filter()}
        GROUP BY 1, 2
    ) source_interval
    GROUP BY 1
),
flow_ts AS (
    SELECT
        {hour_bucket('source_ts')} AS ts,
        AVG(import_mw) AS import_mw,
        AVG(export_mw) AS export_mw,
        AVG(export_mw) - AVG(import_mw) AS net_export_mw
    FROM (
        SELECT
            source_ts,
            SUM(import_mw) AS import_mw,
            SUM(export_mw) AS export_mw
        FROM (
            SELECT "DateTime(UTC)" AS source_ts, "Flow[MW]" AS import_mw, 0::double precision AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "InAreaDisplayName" = '$Country'
              AND {time_filter()}
            UNION ALL
            SELECT "DateTime(UTC)" AS source_ts, 0::double precision AS import_mw, "Flow[MW]" AS export_mw
            FROM entsoe_fms."PhysicalFlows"
            WHERE "OutAreaDisplayName" = '$Country'
              AND {time_filter()}
        ) interval_flows
        GROUP BY 1
    ) hourly_source
    GROUP BY 1
)
SELECT
    p.ts AS timestamp_utc,
    {local_day_expr('p.ts')} AS local_day,
    TO_CHAR({local_day_expr('p.ts')}, 'Dy') AS weekday,
    ROUND(p.price_mwh::numeric, 2) AS price_eur_mwh,
    ROUND(l.load_mw::numeric, 1) AS load_mw,
    ROUND(g.wind_mw::numeric, 1) AS wind_mw,
    ROUND(g.solar_mw::numeric, 1) AS solar_mw,
    ROUND((l.load_mw - COALESCE(g.wind_mw, 0) - COALESCE(g.solar_mw, 0))::numeric, 1) AS residual_load_mw,
    ROUND(s.ps_discharge_mw::numeric, 1) AS pumped_storage_discharge_mw,
    ROUND(s.ps_charge_mw::numeric, 1) AS pumped_storage_charge_mw,
    ROUND(s.battery_discharge_mw::numeric, 1) AS battery_discharge_mw,
    ROUND(s.battery_charge_mw::numeric, 1) AS battery_charge_mw,
    ROUND(f.import_mw::numeric, 1) AS import_mw,
    ROUND(f.export_mw::numeric, 1) AS export_mw,
    ROUND(f.net_export_mw::numeric, 1) AS net_export_delta_mw
FROM prices p
LEFT JOIN load_ts l ON l.ts = p.ts
LEFT JOIN generation_ts g ON g.ts = p.ts
LEFT JOIN storage_ts s ON s.ts = p.ts
LEFT JOIN flow_ts f ON f.ts = p.ts
ORDER BY p.ts
""".strip()


SQL_LONG_NEG_COUNT = SQL_EVENT_NEG_COUNT
SQL_LONG_NEG_SHARE = f"""
WITH {da_hourly_prices_cte()}
SELECT now() AS "time", 100.0 * COUNT(*) FILTER (WHERE price_mwh < 0) / NULLIF(COUNT(*), 0) AS "value"
FROM prices
""".strip()
SQL_LONG_MIN_PRICE = SQL_EVENT_MIN_PRICE


SQL_LONG_AVG_RESIDUAL_NEG = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
),
load_quarter_hour AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
vres_quarter_hour AS (
    SELECT
        {hour_bucket()} AS ts,
        SUM("ActualGenerationOutput[MW]") AS vres_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1
)
SELECT now() AS "time", AVG(l.load_mw - COALESCE(v.vres_mw, 0)) AS "value"
FROM negative_prices p
LEFT JOIN load_quarter_hour l ON l.ts = p.ts
LEFT JOIN vres_quarter_hour v ON v.ts = p.ts
""".strip()


SQL_LONG_MONTHLY_NEG_COUNT = f"""
WITH {da_hourly_prices_cte()}
SELECT date_trunc('month', ts) AS "time", {quarter_hour_hours_expr()} AS "value"
FROM prices
WHERE price_mwh < 0
GROUP BY 1
ORDER BY 1
""".strip()


SQL_LONG_MARKET_SEGMENT_NEG_COUNT = f"""
WITH categorized AS (
    SELECT
        "DateTime(UTC)" AS ts,
        {price_category_case()} AS metric,
        "Price[Currency/MWh]" AS price_mwh
    FROM entsoe_fms."EnergyPrices"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = 'BZN'
      AND {time_filter()}

    UNION ALL

    SELECT
        delivery_start_utc AS ts,
        'EPEX Intraday Auction ' || auction_name AS metric,
        value AS price_mwh
    FROM epex_spot.intraday_auction_prices_volumes
    WHERE market_area = '$Country'
      AND metric = 'price'
      AND {time_filter("delivery_start_utc")}
)
SELECT date_trunc('month', ts) AS "time", metric, {quarter_hour_hours_expr()} AS "value"
FROM categorized
WHERE price_mwh < 0
GROUP BY 1, 2
ORDER BY 1
""".strip()


SQL_LONG_MONTHLY_SEVERITY = f"""
WITH {da_hourly_prices_cte("hourly_prices")},
prices AS (
    SELECT date_trunc('month', ts) AS month, price_mwh
    FROM hourly_prices
    WHERE price_mwh < 0
)
SELECT month AS "time", metric, value
FROM (
    SELECT month, 'Avg negative price' AS metric, AVG(price_mwh) AS value FROM prices GROUP BY 1
    UNION ALL
    SELECT month, 'Min price' AS metric, MIN(price_mwh) AS value FROM prices GROUP BY 1
) s
ORDER BY 1, 2
""".strip()


SQL_LONG_HOUR_PROFILE = f"""
WITH {da_hourly_prices_cte()}
SELECT
    EXTRACT(HOUR FROM ts)::int AS hour_utc,
    ROUND({quarter_hour_hours_expr()}::numeric, 2) AS "Negative hours",
    ROUND(AVG(price_mwh)::numeric, 2) AS "Avg negative price EUR/MWh",
    ROUND(MIN(price_mwh)::numeric, 2) AS "Min price EUR/MWh"
FROM prices
WHERE price_mwh < 0
GROUP BY 1
ORDER BY 1
""".strip()


SQL_LONG_WEEKDAY_PROFILE = f"""
WITH {da_hourly_prices_cte()}
SELECT
    EXTRACT(ISODOW FROM ts)::int AS weekday_no,
    TO_CHAR(ts, 'Dy') AS weekday,
    ROUND({quarter_hour_hours_expr()}::numeric, 2) AS "Negative hours",
    ROUND(AVG(price_mwh)::numeric, 2) AS "Avg negative price EUR/MWh"
FROM prices
WHERE price_mwh < 0
GROUP BY 1, 2
ORDER BY 1
""".strip()


def hour_matrix_sql() -> str:
    hour_columns = []
    for hour in range(24):
        count_expr = f"COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM ts)::int = {hour})"
        hour_columns.append(
            f"ROUND(({quarter_hour_hours_expr(count_expr)})::numeric, 2) AS \"{hour:02d}\""
        )
    return f"""
WITH {da_hourly_prices_cte()}
SELECT
    LPAD(EXTRACT(MONTH FROM ts)::int::text, 2, '0') || ' ' || TO_CHAR(ts, 'Mon') AS month,
    {",\n    ".join(hour_columns)}
FROM prices
WHERE price_mwh < 0
GROUP BY EXTRACT(MONTH FROM ts)::int, month
ORDER BY EXTRACT(MONTH FROM MIN(ts))::int
""".strip()


SQL_LONG_PRICE_BANDS = f"""
WITH {da_hourly_prices_cte("prices")},
categorized AS (
    SELECT
        price_mwh,
        CASE
            WHEN price_mwh < -100 THEN '1 < -100'
            WHEN price_mwh < -50 THEN '2 -100 to -50'
            WHEN price_mwh < 0 THEN '3 -50 to 0'
            WHEN price_mwh < 25 THEN '4 0 to 25'
            WHEN price_mwh < 50 THEN '5 25 to 50'
            ELSE '6 >= 50'
        END AS price_band
    FROM prices
)
SELECT
    price_band,
    ROUND({quarter_hour_hours_expr()}::numeric, 2) AS "Hours",
    ROUND(AVG(price_mwh)::numeric, 2) AS "Avg price EUR/MWh"
FROM categorized
GROUP BY 1
ORDER BY 1
""".strip()


SQL_LONG_DRIVER_SUMMARY = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts, price_mwh
    FROM prices
    WHERE price_mwh < 0
),
load_quarter_hour AS (
    SELECT {hour_bucket()} AS ts, AVG("TotalLoad[MW]") AS load_mw
    FROM entsoe_fms."ActualTotalLoad"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND {time_filter()}
    GROUP BY 1
),
gen_quarter_hour AS (
    SELECT
        {hour_bucket()} AS ts,
        SUM(CASE WHEN "ProductionType" = 'Solar' THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS solar_mw,
        SUM(CASE WHEN "ProductionType" IN ('Wind Onshore', 'Wind Offshore') THEN "ActualGenerationOutput[MW]" ELSE 0 END) AS wind_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1
),
storage_quarter_hour AS (
    SELECT
        {hour_bucket()} AS ts,
        SUM(COALESCE(CASE WHEN "ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE "ActualConsumption[MW]" END, 0)) AS storage_charge_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND ("ProductionType" = 'Hydro Pumped Storage' OR "ProductionType" ILIKE '%Battery%')
      AND {time_filter()}
    GROUP BY 1
),
flow_quarter_hour AS (
    SELECT
        ts,
        SUM(export_mw) - SUM(import_mw) AS net_export_mw
    FROM (
        SELECT {hour_bucket()} AS ts, "Flow[MW]" AS import_mw, 0::double precision AS export_mw
        FROM entsoe_fms."PhysicalFlows"
        WHERE "InAreaDisplayName" = '$Country'
          AND {time_filter()}
        UNION ALL
        SELECT {hour_bucket()} AS ts, 0::double precision AS import_mw, "Flow[MW]" AS export_mw
        FROM entsoe_fms."PhysicalFlows"
        WHERE "OutAreaDisplayName" = '$Country'
          AND {time_filter()}
    ) x
    GROUP BY 1
)
SELECT date_trunc('month', p.ts) AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT p.ts, 'Load during neg prices' AS metric, l.load_mw AS value
    FROM negative_prices p LEFT JOIN load_quarter_hour l ON l.ts = p.ts
    UNION ALL
    SELECT p.ts, 'Wind+Solar during neg prices' AS metric, COALESCE(g.wind_mw, 0) + COALESCE(g.solar_mw, 0) AS value
    FROM negative_prices p LEFT JOIN gen_quarter_hour g ON g.ts = p.ts
    UNION ALL
    SELECT p.ts, 'Residual load during neg prices' AS metric, l.load_mw - COALESCE(g.wind_mw, 0) - COALESCE(g.solar_mw, 0) AS value
    FROM negative_prices p LEFT JOIN load_quarter_hour l ON l.ts = p.ts LEFT JOIN gen_quarter_hour g ON g.ts = p.ts
    UNION ALL
    SELECT p.ts, 'Storage charge during neg prices' AS metric, storage_charge_mw AS value
    FROM negative_prices p LEFT JOIN storage_quarter_hour s ON s.ts = p.ts
    UNION ALL
    SELECT p.ts, 'Net export during neg prices' AS metric, net_export_mw AS value
    FROM negative_prices p LEFT JOIN flow_quarter_hour f ON f.ts = p.ts
) s
JOIN negative_prices p ON p.ts = s.ts
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


SQL_LONG_STORAGE_BY_PRICE_BAND = f"""
WITH {da_hourly_prices_cte("prices")},
price_bands AS (
    SELECT
        ts,
        CASE
            WHEN price_mwh < 0 THEN '1 <0'
            WHEN price_mwh < 25 THEN '2 0-25'
            WHEN price_mwh < 50 THEN '3 25-50'
            WHEN price_mwh < 100 THEN '4 50-100'
            ELSE '5 >=100'
        END AS price_band
    FROM prices
),
storage AS (
    SELECT
        {hour_bucket('g."DateTime(UTC)"')} AS ts,
        SUM(CASE WHEN g."ProductionType" = 'Hydro Pumped Storage' THEN g."ActualGenerationOutput[MW]" ELSE 0 END) AS ps_discharge_mw,
        SUM(CASE WHEN g."ProductionType" = 'Hydro Pumped Storage' THEN COALESCE(CASE WHEN g."ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE g."ActualConsumption[MW]" END, 0) ELSE 0 END) AS ps_charge_mw,
        SUM(CASE WHEN g."ProductionType" ILIKE '%Battery%' THEN g."ActualGenerationOutput[MW]" ELSE 0 END) AS battery_discharge_mw,
        SUM(CASE WHEN g."ProductionType" ILIKE '%Battery%' THEN COALESCE(CASE WHEN g."ActualConsumption[MW]"::text = 'NaN' THEN NULL ELSE g."ActualConsumption[MW]" END, 0) ELSE 0 END) AS battery_charge_mw
    FROM entsoe_fms."AggregatedGenerationPerType" g
    WHERE g."AreaDisplayName" = '$Country'
      AND g."AreaTypeCode" = '$Area_Type'
      AND (g."ProductionType" = 'Hydro Pumped Storage' OR g."ProductionType" ILIKE '%Battery%')
      AND {time_filter('g."DateTime(UTC)"')}
    GROUP BY 1
),
joined AS (
    SELECT p.price_band, s.*
    FROM price_bands p
    JOIN storage s ON s.ts = p.ts
)
SELECT
    price_band,
    ROUND(AVG(ps_discharge_mw)::numeric, 1) AS "Pumped discharge MW",
    ROUND(AVG(ps_charge_mw)::numeric, 1) AS "Pumped charge MW",
    ROUND(AVG(battery_discharge_mw)::numeric, 1) AS "Battery discharge MW",
    ROUND(AVG(battery_charge_mw)::numeric, 1) AS "Battery charge MW"
FROM joined
GROUP BY 1
ORDER BY 1
""".strip()


SQL_LONG_NEIGHBOUR_MONTHLY_SPREAD = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
{da_hourly_prices_cte("home_prices")},
{da_hourly_area_prices_cte()},
paired AS (
    SELECT h.ts, n.neighbour, h.price_mwh - n.price_mwh AS spread_eur_mwh
    FROM home_prices h
    JOIN neighbour_prices n ON n.ts = h.ts
)
SELECT date_trunc('month', ts) AS "time", neighbour AS metric, AVG(spread_eur_mwh) AS "value"
FROM paired
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


SQL_LONG_NEIGHBOUR_NEGATIVE_COOCCURRENCE = f"""
WITH connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
{da_hourly_prices_cte("home_prices")},
{da_hourly_area_prices_cte()},
paired AS (
    SELECT
        h.ts,
        n.neighbour,
        h.price_mwh AS home_price,
        n.price_mwh AS neighbour_price,
        h.price_mwh - n.price_mwh AS spread_eur_mwh
    FROM home_prices h
    JOIN neighbour_prices n ON n.ts = h.ts
)
SELECT
    neighbour,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE home_price < 0)")}::numeric, 2) AS home_negative_hours,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE neighbour_price < 0)")}::numeric, 2) AS neighbour_negative_hours,
    ROUND({quarter_hour_hours_expr("COUNT(*) FILTER (WHERE home_price < 0 AND neighbour_price < 0)")}::numeric, 2) AS simultaneous_negative_hours,
    ROUND((100.0 * COUNT(*) FILTER (WHERE home_price < 0 AND neighbour_price < 0) / NULLIF(COUNT(*) FILTER (WHERE home_price < 0), 0))::numeric, 1) AS simultaneous_share_of_home_negative_pct,
    ROUND(AVG(spread_eur_mwh) FILTER (WHERE home_price < 0)::numeric, 2) AS avg_spread_when_home_negative_eur_mwh,
    ROUND(MIN(neighbour_price)::numeric, 2) AS min_neighbour_price_eur_mwh
FROM paired
GROUP BY 1
ORDER BY simultaneous_negative_hours DESC, simultaneous_share_of_home_negative_pct DESC NULLS LAST, neighbour
""".strip()


SQL_LONG_CROSS_BORDER_NEGATIVE = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
),
connected_neighbours AS (
    SELECT DISTINCT x.neighbour
    FROM (
        SELECT "InAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "OutAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
        UNION
        SELECT "OutAreaDisplayName" AS neighbour
        FROM entsoe_fms."ForecastedTransferCapacities"
        WHERE "InAreaDisplayName" = '$Country'
          AND "DateTime(UTC)" >= now() - interval '730 days'
    ) x
    WHERE x.neighbour <> '$Country'
),
flows AS (
    SELECT p.ts, "OutAreaDisplayName" AS neighbour, 'Import'::text AS direction, "Flow[MW]" AS flow_mw
    FROM negative_prices p
    JOIN entsoe_fms."PhysicalFlows" f
      ON {hour_bucket('f."DateTime(UTC)"')} = p.ts
     AND f."InAreaDisplayName" = '$Country'
     AND f."OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
    UNION ALL
    SELECT p.ts, "InAreaDisplayName" AS neighbour, 'Export'::text AS direction, "Flow[MW]" AS flow_mw
    FROM negative_prices p
    JOIN entsoe_fms."PhysicalFlows" f
      ON {hour_bucket('f."DateTime(UTC)"')} = p.ts
     AND f."OutAreaDisplayName" = '$Country'
     AND f."InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
),
capacities AS (
    SELECT p.ts, c."OutAreaDisplayName" AS neighbour, 'Import'::text AS direction, c."ForecastTransferCapacity[MW]" AS capacity_mw
    FROM negative_prices p
    JOIN entsoe_fms."ForecastedTransferCapacities" c
      ON c."DateTime(UTC)" = p.ts
     AND c."InAreaDisplayName" = '$Country'
     AND c."OutAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
     AND c."ContractType" = 'Day-ahead'
    UNION ALL
    SELECT p.ts, c."InAreaDisplayName" AS neighbour, 'Export'::text AS direction, c."ForecastTransferCapacity[MW]" AS capacity_mw
    FROM negative_prices p
    JOIN entsoe_fms."ForecastedTransferCapacities" c
      ON c."DateTime(UTC)" = p.ts
     AND c."OutAreaDisplayName" = '$Country'
     AND c."InAreaDisplayName" IN (SELECT neighbour FROM connected_neighbours)
     AND c."ContractType" = 'Day-ahead'
)
SELECT
    COALESCE(f.neighbour, c.neighbour) AS neighbour,
    COALESCE(f.direction, c.direction) AS direction,
    ROUND(AVG(f.flow_mw)::numeric, 1) AS avg_physical_flow_mw,
    ROUND(AVG(c.capacity_mw)::numeric, 1) AS avg_capacity_mw,
    ROUND(({quarter_hour_hours_expr("COUNT(DISTINCT COALESCE(f.ts, c.ts))")})::numeric, 2) AS negative_price_hours
FROM flows f
FULL OUTER JOIN capacities c
  ON c.ts = f.ts AND c.neighbour = f.neighbour AND c.direction = f.direction
GROUP BY 1, 2
ORDER BY negative_price_hours DESC, avg_physical_flow_mw DESC NULLS LAST
""".strip()


SQL_LONG_FORECAST_ERRORS_NEGATIVE = f"""
WITH {da_hourly_prices_cte()},
negative_prices AS (
    SELECT ts
    FROM prices
    WHERE price_mwh < 0
),
actual AS (
    SELECT
        {hour_bucket()} AS ts,
        "ProductionType" AS production_type,
        AVG("ActualGenerationOutput[MW]") AS actual_mw
    FROM entsoe_fms."AggregatedGenerationPerType"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1, 2
),
forecast AS (
    SELECT
        {hour_bucket()} AS ts,
        "ProductionType" AS production_type,
        AVG("DayAheadGenerationForecast[MW]") AS day_ahead_mw,
        AVG("IntradayGenerationForecast[MW]") AS intraday_mw,
        AVG("CurrentGenerationForecast[MW]") AS current_mw
    FROM entsoe_fms."GenerationForecastsForWindAndSolar"
    WHERE "AreaDisplayName" = '$Country'
      AND "AreaTypeCode" = '$Area_Type'
      AND "ProductionType" IN ('Solar', 'Wind Onshore', 'Wind Offshore')
      AND {time_filter()}
    GROUP BY 1, 2
),
joined AS (
    SELECT
        p.ts,
        a.production_type,
        AVG(f.day_ahead_mw - a.actual_mw) AS day_ahead_error_mw,
        AVG(f.intraday_mw - a.actual_mw) AS intraday_error_mw,
        AVG(f.current_mw - a.actual_mw) AS current_error_mw
    FROM negative_prices p
    LEFT JOIN actual a ON a.ts = p.ts
    LEFT JOIN forecast f ON f.ts = a.ts AND f.production_type = a.production_type
    GROUP BY 1, 2
)
SELECT date_trunc('month', ts) AS "time", metric, AVG(value) AS "value"
FROM (
    SELECT ts, production_type || ' day-ahead error during neg prices' AS metric, day_ahead_error_mw AS value FROM joined
    UNION ALL SELECT ts, production_type || ' intraday error during neg prices' AS metric, intraday_error_mw AS value FROM joined
    UNION ALL SELECT ts, production_type || ' continuous error during neg prices' AS metric, current_error_mw AS value FROM joined
) s
WHERE metric IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


SQL_LONG_REVENUE_PROXY = SQL_REVENUE_PROXY_EVENT.replace("LIMIT 20", "LIMIT 30")


SQL_OPTIONAL_DATA_AVAILABILITY = """
SELECT
    source,
    table_ref,
    table_available,
    note
FROM (
    VALUES
        ('Curtailment / redispatch', 'netztransparenz.redispatch', to_regclass('netztransparenz.redispatch') IS NOT NULL, 'Redispatch records; useful curtailment proxy, not direct curtailed-energy measurement.'),
        ('Balancing energy utilisation', 'netztransparenz.vermarktung_inanspruchnahme_ausgleichsenergie', to_regclass('netztransparenz.vermarktung_inanspruchnahme_ausgleichsenergie') IS NOT NULL, 'Ausgleichsenergie utilisation from Netztransparenz; source requires credentials.'),
        ('aFRR energy prices', 'public.afrr_ergebnisse_regelarbeit', to_regclass('public.afrr_ergebnisse_regelarbeit') IS NOT NULL, 'Regelarbeit result table includes min/average/marginal energy-price columns.'),
        ('mFRR energy prices', 'public.mfrr_ergebnisse_regelarbeit', to_regclass('public.mfrr_ergebnisse_regelarbeit') IS NOT NULL, 'Regelarbeit result table includes min/average/marginal energy-price columns.')
) AS availability(source, table_ref, table_available, note)
ORDER BY source
""".strip()


def event_dashboard() -> dict:
    panels = [
        text_panel(
            1,
            "Scope",
            "Event dashboard for the German local weekend 2026-04-25 and 2026-04-26. The default range is 2026-04-24 22:00 UTC to 2026-04-26 21:59:59 UTC, matching CEST Saturday/Sunday local days. Core KPI and analysis panels use the main day-ahead auction from ENTSO-E Sequence 1 on a 15-minute basis; Sequence 2 is shown separately as the EXAA day-ahead auction. EPEX intraday auction prices are added as separate products where available. The Sunday KPI cards use local day 2026-04-26 only. Cross-border delta is net export: exports minus imports.",
            {"h": 3, "w": 24, "x": 0, "y": 0},
        ),
        stat_panel(2, "Minimum Day-Ahead Price", SQL_EVENT_MIN_PRICE, {"h": 4, "w": 6, "x": 0, "y": 3}, UNIT_EUR_PER_MWH, decimals=2),
        stat_panel(3, "Negative Day-Ahead Hours", SQL_EVENT_NEG_COUNT, {"h": 4, "w": 6, "x": 6, "y": 3}, UNIT_HOURS, decimals=2),
        stat_panel(26, "Negative Hours (Sunday)", SQL_EVENT_NEG_COUNT_SUNDAY, {"h": 4, "w": 6, "x": 12, "y": 3}, UNIT_HOURS, decimals=2),
        stat_panel(4, "Avg Negative Price", SQL_EVENT_AVG_NEG, {"h": 4, "w": 6, "x": 18, "y": 3}, UNIT_EUR_PER_MWH, decimals=2),
        stat_panel(5, "Longest Negative Block", SQL_EVENT_LONGEST_BLOCK, {"h": 4, "w": 8, "x": 0, "y": 7}, UNIT_HOURS, decimals=2),
        stat_panel(6, "Load in Negative Hours", SQL_EVENT_LOAD_NEG, {"h": 4, "w": 8, "x": 8, "y": 7}, UNIT_MWH, decimals=1),
        stat_panel(27, "Load in Negative Hours (Sunday)", SQL_EVENT_LOAD_NEG_SUNDAY, {"h": 4, "w": 8, "x": 16, "y": 7}, UNIT_MWH, decimals=1),
        table_panel(23, "Saturday vs Sunday Summary", SQL_EVENT_DAILY_COMPARISON, {"h": 6, "w": 24, "x": 0, "y": 11}),
        timeseries_panel(7, "Price Products incl. EPEX Intraday", SQL_PRICE_COMPARISON, {"h": 8, "w": 16, "x": 0, "y": 17}, unit="currencyEUR", decimals=2, description="Price-only panel. KPI and analysis panels use ENTSO-E Sequence 1 as the main day-ahead reference; Sequence 2 (EXAA) and EPEX intraday auction products are shown separately at native timestamps."),
        table_panel(8, "Available Price Products incl. EPEX", SQL_PRICE_PRODUCT_AVAILABILITY, {"h": 8, "w": 8, "x": 16, "y": 17}),
        timeseries_panel(9, "Demand, Wind/Solar and Residual Load", SQL_DEMAND_WIND_SOLAR_RESIDUAL, {"h": 8, "w": 12, "x": 0, "y": 25}, unit="megwatt", decimals=1, overrides=DEMAND_WIND_SOLAR_OVERRIDES),
        timeseries_panel(10, "Demand Coverage Stack", SQL_DEMAND_WIND_SOLAR_STACKED, {"h": 8, "w": 12, "x": 12, "y": 25}, unit="megwatt", decimals=1, stacking="normal", fill_opacity=35, overrides=DEMAND_WIND_SOLAR_OVERRIDES),
        timeseries_panel(25, "Residual Load incl. Imports and Exports", SQL_DEMAND_WIND_SOLAR_RESIDUAL_TRADE, {"h": 8, "w": 12, "x": 0, "y": 33}, unit="megwatt", decimals=1, overrides=DEMAND_WIND_SOLAR_OVERRIDES, description="Residual Load = Load - Wind - Solar. Residual Load incl. Trade = Load - Wind - Solar + Exports - Imports."),
        timeseries_panel(28, "Demand Coverage incl. Trade Stack", SQL_DEMAND_WIND_SOLAR_TRADE_STACKED, {"h": 8, "w": 12, "x": 12, "y": 33}, unit="megwatt", decimals=1, stacking="normal", fill_opacity=35, overrides=DEMAND_WIND_SOLAR_OVERRIDES, description="Stacked demand coverage with trade-adjusted residual load: Residual Load incl. Trade = Load - Wind - Solar + Exports - Imports."),
        timeseries_panel(11, "Generation Mix", SQL_GENERATION_MIX, {"h": 9, "w": 12, "x": 0, "y": 41}, unit="megwatt", decimals=1, stacking="normal", fill_opacity=20, overrides=GENERATION_MIX_OVERRIDES),
        timeseries_panel(12, "Storage Response", SQL_STORAGE_RESPONSE, {"h": 9, "w": 12, "x": 12, "y": 41}, unit="megwatt", decimals=1, description="Positive values discharge/generation; negative values charge/pumping. Battery series appear only if ENTSO-E production types contain battery data."),
        timeseries_panel(13, "Forecast vs Actual by Technology", SQL_FORECAST_BY_TECHNOLOGY, {"h": 9, "w": 12, "x": 0, "y": 50}, unit="megwatt", decimals=1, overrides=FORECAST_LINE_OVERRIDES),
        timeseries_panel(14, "Forecast Stacks by Family", SQL_FORECAST_BY_TECHNOLOGY, {"h": 9, "w": 12, "x": 12, "y": 50}, unit="megwatt", decimals=1, stacking="none", fill_opacity=20, overrides=FORECAST_STACK_OVERRIDES, description="Actual, day-ahead, intraday and continuous forecasts are each stacked across technologies in separate stacking groups."),
        timeseries_panel(15, "Neighbour Day-Ahead Prices", SQL_NEIGHBOUR_PRICE_COMPARISON, {"h": 9, "w": 12, "x": 0, "y": 59}, unit="currencyEUR", decimals=2),
        timeseries_panel(16, "Physical Imports, Exports and Net Position", SQL_CROSS_BORDER_FLOWS, {"h": 9, "w": 12, "x": 12, "y": 59}, unit="megwatt", decimals=1, overrides=DEMAND_WIND_SOLAR_OVERRIDES, description="Trade convention: positive values are imports, negative values are exports. Net Position = Imports - Exports."),
        table_panel(17, "Border Capacity and Price Spread", SQL_BORDER_CAPACITY_TABLE, {"h": 8, "w": 12, "x": 0, "y": 68}),
        table_panel(24, "Cross-Border Delta: Sunday minus Saturday", SQL_CROSS_BORDER_WEEKEND_DELTA, {"h": 8, "w": 12, "x": 12, "y": 68}),
        table_panel(18, "Neighbour Price Comparison", SQL_NEIGHBOUR_PRICE_SPREAD_EVENT, {"h": 8, "w": 12, "x": 0, "y": 76}),
        timeseries_panel(19, "Net Cross-Border Positions by Country", SQL_CROSS_BORDER_NET_POSITIONS, {"h": 8, "w": 12, "x": 12, "y": 76}, unit="megwatt", decimals=1, stacking="normal", fill_opacity=90, draw_style="bars", line_width=0, bar_width_factor=0.8, description="Stacked country-level net positions. Positive values are imports, negative values are exports. Internal zones such as DE-LU and DE TSO areas are normalised to a single country code and the home country is excluded."),
        table_panel(20, "Revenue Proxy During Negative Prices", SQL_REVENUE_PROXY_EVENT, {"h": 9, "w": 12, "x": 0, "y": 84}),
        table_panel(21, "Quarter-Hour Context Table", SQL_EVENT_CONTEXT_TABLE, {"h": 9, "w": 12, "x": 12, "y": 84}),
        timeseries_panel(22, "Cross-Border Capacity Utilisation", SQL_CROSS_BORDER_CAPACITY_UTILISATION, {"h": 8, "w": 24, "x": 0, "y": 93}, unit="percent", decimals=1, description="Aggregate cross-border utilisation by direction: actual physical imports or exports divided by available transfer capacity."),
    ]
    return dashboard_shell(
        title="ENTSOE Negative Prices - Weekend 2026-04-25/26",
        uid="entsoe-negative-prices-event-20260426",
        description="Focused analysis dashboard for negative electricity prices over Saturday and Sunday 2026-04-25/26, including prices, residual load, generation mix, storage, cross-border flows, forecasts, cross-border deltas and revenue proxy.",
        tags=["entsoe", "oeds", "negative-prices", "market", "event"],
        panels=panels,
        time_from="2026-04-24T22:00:00Z",
        time_to="2026-04-26T21:59:59Z",
        include_transfer_contract=False,
    )


def long_term_dashboard() -> dict:
    panels = [
        text_panel(
            1,
            "Scope",
            "Long-term analysis dashboard for negative prices. Use the time picker for the historical window. Core metrics use ENTSO-E Sequence 1 as the main day-ahead reference on a 15-minute basis and convert quarter-hour counts to hours where appropriate; product comparison panels keep EXAA, other ENTSO-E intraday products and EPEX intraday auction prices separate where populated.",
            {"h": 3, "w": 24, "x": 0, "y": 0},
        ),
        stat_panel(2, "Negative Day-Ahead Hours", SQL_LONG_NEG_COUNT, {"h": 4, "w": 6, "x": 0, "y": 3}, UNIT_HOURS, decimals=2),
        stat_panel(3, "Negative Share", SQL_LONG_NEG_SHARE, {"h": 4, "w": 6, "x": 6, "y": 3}, "percent", decimals=2),
        stat_panel(4, "Minimum Day-Ahead Price", SQL_LONG_MIN_PRICE, {"h": 4, "w": 6, "x": 12, "y": 3}, UNIT_EUR_PER_MWH, decimals=2),
        stat_panel(5, "Avg Residual Load in Negative Hours", SQL_LONG_AVG_RESIDUAL_NEG, {"h": 4, "w": 6, "x": 18, "y": 3}, "megwatt", decimals=1),
        timeseries_panel(6, "Monthly Negative Day-Ahead Hours", SQL_LONG_MONTHLY_NEG_COUNT, {"h": 8, "w": 12, "x": 0, "y": 7}, unit="short", decimals=2),
        timeseries_panel(7, "Monthly Negative Hours by Price Product", SQL_LONG_MARKET_SEGMENT_NEG_COUNT, {"h": 8, "w": 12, "x": 12, "y": 7}, unit="short", decimals=2),
        timeseries_panel(8, "Monthly Negative Price Severity", SQL_LONG_MONTHLY_SEVERITY, {"h": 8, "w": 12, "x": 0, "y": 15}, unit="currencyEUR", decimals=2),
        timeseries_panel(9, "Monthly Drivers During Negative Prices", SQL_LONG_DRIVER_SUMMARY, {"h": 8, "w": 12, "x": 12, "y": 15}, unit="megwatt", decimals=1),
        barchart_panel(10, "Hour-of-Day Negative Price Profile", SQL_LONG_HOUR_PROFILE, {"h": 8, "w": 12, "x": 0, "y": 23}, "hour_utc"),
        barchart_panel(11, "Weekday Negative Price Profile", SQL_LONG_WEEKDAY_PROFILE, {"h": 8, "w": 12, "x": 12, "y": 23}, "weekday"),
        table_panel(12, "Month x Hour Negative Price Matrix", hour_matrix_sql(), {"h": 9, "w": 24, "x": 0, "y": 31}),
        barchart_panel(13, "Price Band Distribution", SQL_LONG_PRICE_BANDS, {"h": 8, "w": 12, "x": 0, "y": 40}, "price_band"),
        barchart_panel(14, "Storage Behaviour by Price Band", SQL_LONG_STORAGE_BY_PRICE_BAND, {"h": 8, "w": 12, "x": 12, "y": 40}, "price_band"),
        timeseries_panel(15, "Monthly Home-Neighbour Price Spread", SQL_LONG_NEIGHBOUR_MONTHLY_SPREAD, {"h": 9, "w": 12, "x": 0, "y": 48}, unit="currencyEUR", decimals=2),
        table_panel(16, "Neighbour Negative Price Co-Occurrence", SQL_LONG_NEIGHBOUR_NEGATIVE_COOCCURRENCE, {"h": 9, "w": 12, "x": 12, "y": 48}),
        table_panel(17, "Cross-Border Response in Negative Hours", SQL_LONG_CROSS_BORDER_NEGATIVE, {"h": 9, "w": 12, "x": 0, "y": 57}),
        timeseries_panel(18, "Wind/Solar Forecast Error by Technology", SQL_LONG_FORECAST_ERRORS_NEGATIVE, {"h": 9, "w": 12, "x": 12, "y": 57}, unit="megwatt", decimals=1),
        table_panel(19, "Revenue Proxy During Negative Prices", SQL_LONG_REVENUE_PROXY, {"h": 10, "w": 24, "x": 0, "y": 66}),
    ]
    return dashboard_shell(
        title="ENTSOE Negative Prices - Long-Term Analysis",
        uid="entsoe-negative-prices-long-term",
        description="Long-term analysis of negative electricity prices, including market-segment comparison, residual load drivers, storage behaviour, cross-border response, forecast errors and revenue proxy.",
        tags=["entsoe", "oeds", "negative-prices", "market", "long-term"],
        panels=panels,
        time_from="now-2y",
        time_to="now",
        include_transfer_contract=False,
    )


def write_dashboard(path: Path, dashboard: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dashboard, handle, indent=4)
        handle.write("\n")


def main() -> None:
    write_dashboard(OUT_EVENT, event_dashboard())
    write_dashboard(OUT_LONG_TERM, long_term_dashboard())


if __name__ == "__main__":
    main()
