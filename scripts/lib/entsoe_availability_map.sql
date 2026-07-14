-- Derived live availability layer for the ENTSO-E FMS dashboard.
-- The hourly refresh is triggered via scripts/refresh_entsoe_availability_map.py.

CREATE SCHEMA IF NOT EXISTS entsoe_availability_map;

CREATE TABLE IF NOT EXISTS entsoe_availability_map.asset_mapping_override (
    asset_code text PRIMARY KEY,
    override_asset_name text,
    override_installed_capacity_mw double precision,
    override_lon double precision,
    override_lat double precision,
    override_country text,
    note text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW entsoe_availability_map.v_area_to_country_map AS
WITH mapping(map_key, country_name) AS (
    VALUES
        ('Albania (AL)', 'Albania'),
        ('Austria (AT)', 'Austria'),
        ('Belgium (BE)', 'Belgium'),
        ('Bosnia and Herz. (BA)', 'Bosnia and Herzegovina'),
        ('Bulgaria (BG)', 'Bulgaria'),
        ('Croatia (HR)', 'Croatia'),
        ('Cyprus (CY)', 'Cyprus'),
        ('Czech Republic (CZ)', 'Czechia'),
        ('Denmark (DK)', 'Denmark'),
        ('DK', 'Denmark'),
        ('DK1', 'Denmark'),
        ('DK2', 'Denmark'),
        ('Estonia (EE)', 'Estonia'),
        ('Finland (FI)', 'Finland'),
        ('France (FR)', 'France'),
        ('Germany (DE)', 'Germany'),
        ('DE(50Hertz)', 'Germany'),
        ('DE(Amprion)', 'Germany'),
        ('DE(TenneT GER)', 'Germany'),
        ('DE(TransnetBW)', 'Germany'),
        ('DE-LU', 'Germany'),
        ('Greece (GR)', 'Greece'),
        ('Hungary (HU)', 'Hungary'),
        ('Ireland (IE)', 'Ireland'),
        ('IE(SEM)', 'Ireland'),
        ('NIE', 'United Kingdom'),
        ('Italy (IT)', 'Italy'),
        ('IT-Calabria', 'Italy'),
        ('IT-Centre-North', 'Italy'),
        ('IT-Centre-South', 'Italy'),
        ('IT-North', 'Italy'),
        ('IT-Sardinia', 'Italy'),
        ('IT-Sicily', 'Italy'),
        ('IT-South', 'Italy'),
        ('Kosovo (XK)', 'Kosovo'),
        ('Latvia (LV)', 'Latvia'),
        ('Lithuania (LT)', 'Lithuania'),
        ('Luxembourg (LU)', 'Luxembourg'),
        ('Moldova (MD)', 'Moldova'),
        ('Montenegro (ME)', 'Montenegro'),
        ('Netherlands (NL)', 'Netherlands'),
        ('North Macedonia (MK)', 'North Macedonia'),
        ('Norway (NO)', 'Norway'),
        ('NO1', 'Norway'),
        ('NO2', 'Norway'),
        ('NO3', 'Norway'),
        ('NO4', 'Norway'),
        ('NO5', 'Norway'),
        ('Poland (PL)', 'Poland'),
        ('Portugal (PT)', 'Portugal'),
        ('Romania (RO)', 'Romania'),
        ('Serbia (RS)', 'Serbia'),
        ('Slovakia (SK)', 'Slovakia'),
        ('Slovenia (SI)', 'Slovenia'),
        ('Spain (ES)', 'Spain'),
        ('Sweden (SE)', 'Sweden'),
        ('SE1', 'Sweden'),
        ('SE2', 'Sweden'),
        ('SE3', 'Sweden'),
        ('SE4', 'Sweden'),
        ('Switzerland (CH)', 'Switzerland'),
        ('United Kingdom (UK)', 'United Kingdom'),
        ('Ukraine (UA)', 'Ukraine')
)
SELECT map_key, country_name
FROM mapping;

-- Approximate country display points based on existing mapped plant coordinates.
-- This is operationally simple and avoids an extra geographic source dependency.
CREATE OR REPLACE VIEW entsoe_availability_map.v_country_display_point AS
SELECT
    country AS country_key,
    country AS country_name,
    AVG(lon)::double precision AS lon,
    AVG(lat)::double precision AS lat
FROM entsoe_fms.powersystemdata
WHERE country IS NOT NULL
  AND lon IS NOT NULL
  AND lat IS NOT NULL
GROUP BY country;

CREATE OR REPLACE VIEW entsoe_availability_map.v_outage_event_latest AS
WITH ranked AS (
    SELECT
        o.*,
        row_number() OVER (
            PARTITION BY
                o."InstanceCode",
                o."AssetCode",
                o."StartTimeSeries(UTC)",
                o."EndTimeSeries(UTC)"
            ORDER BY
                o."Version" DESC,
                o."UpdateTime(UTC)" DESC
        ) AS version_rank
    FROM entsoe_fms."UnavailabilityOfProductionAndGenerationUnits" o
),
latest AS (
    SELECT *
    FROM ranked
    WHERE version_rank = 1
      AND "Status" = 'Active'
      AND COALESCE("EndTimeSeries(UTC)", "EndOutage(UTC)") > now()
)
SELECT
    "InstanceCode" AS instance_code,
    "Version" AS version,
    lower("Type") AS layer,
    "AreaDisplayName" AS area_display_name,
    "AreaMapCode" AS area_map_code,
    "AssetCode" AS asset_code,
    "AssetName" AS asset_name,
    "AssetType" AS asset_type,
    "ProductionType" AS production_type,
    "AvailableCapacity[MW]"::double precision AS available_capacity_mw,
    "Reason" AS reason,
    "StartTimeSeries(UTC)" AS start_timeseries_utc,
    "EndTimeSeries(UTC)" AS end_timeseries_utc,
    "UpdateTime(UTC)" AS update_time_utc
FROM latest;

CREATE OR REPLACE VIEW entsoe_availability_map.v_asset_reference AS
WITH outage_assets AS (
    SELECT DISTINCT
        o.asset_code,
        o.asset_name,
        o.asset_type,
        o.production_type,
        o.area_display_name,
        o.area_map_code,
        o.update_time_utc
    FROM entsoe_availability_map.v_outage_event_latest o
),
prod_unit_latest AS (
    SELECT DISTINCT ON ("ProductionUnitCode")
        "ProductionUnitCode" AS production_unit_code,
        "ProductionUnitName" AS production_unit_name,
        "ProductionType" AS production_type,
        "InstalledCapacity(MW)"::double precision AS installed_capacity_mw,
        "UpdateTime(UTC)" AS update_time_utc
    FROM entsoe_fms."InstalledGenerationCapacityPerProductionUnit"
    ORDER BY
        "ProductionUnitCode",
        COALESCE("ValidTo", "ValidFrom") DESC,
        "UpdateTime(UTC)" DESC
)
SELECT
    a.asset_code,
    COALESCE(m.override_asset_name, a.asset_name, p.name, pu.production_unit_name) AS asset_name,
    a.asset_type,
    COALESCE(a.production_type, pu.production_type, p.fuel_type) AS production_type,
    COALESCE(m.override_installed_capacity_mw, pu.installed_capacity_mw, p.capacity) AS installed_capacity_mw,
    COALESCE(m.override_country, p.country, map.country_name, a.area_map_code) AS country_key,
    COALESCE(m.override_lon, p.lon) AS lon,
    COALESCE(m.override_lat, p.lat) AS lat,
    CASE
        WHEN COALESCE(m.override_lon, p.lon) IS NOT NULL AND COALESCE(m.override_lat, p.lat) IS NOT NULL THEN 'exact'
        ELSE 'unknown'
    END AS location_tag,
    a.area_display_name,
    a.area_map_code,
    a.update_time_utc AS last_seen_update_time_utc
FROM outage_assets a
LEFT JOIN entsoe_availability_map.asset_mapping_override m
    ON m.asset_code = a.asset_code
LEFT JOIN entsoe_fms.powersystemdata p
    ON p.eic_code = a.asset_code
LEFT JOIN prod_unit_latest pu
    ON pu.production_unit_code = a.asset_code
LEFT JOIN entsoe_availability_map.v_area_to_country_map map
    ON map.map_key = a.area_display_name
    OR map.map_key = a.area_map_code;

DROP VIEW IF EXISTS entsoe_availability_map.v_availability_map_points_next_24h;
DROP MATERIALIZED VIEW IF EXISTS entsoe_availability_map.mv_availability_country_unknown_agg_next_24h;
DROP MATERIALIZED VIEW IF EXISTS entsoe_availability_map.mv_availability_next_24h;

CREATE MATERIALIZED VIEW entsoe_availability_map.mv_availability_next_24h AS
WITH hours AS (
    SELECT
        generate_series(
            date_trunc('hour', now()),
            date_trunc('hour', now()) + interval '23 hours',
            interval '1 hour'
        ) AS snapshot_utc
),
asset_hours AS (
    SELECT
        h.snapshot_utc,
        a.asset_code,
        a.asset_name,
        a.asset_type,
        a.production_type,
        a.installed_capacity_mw,
        a.country_key,
        a.lon,
        a.lat,
        a.location_tag,
        a.area_display_name,
        a.area_map_code
    FROM hours h
    CROSS JOIN entsoe_availability_map.v_asset_reference a
),
hourly_overlap AS (
    SELECT
        ah.snapshot_utc,
        ah.asset_code,
        ah.asset_name,
        ah.asset_type,
        ah.production_type,
        ah.installed_capacity_mw,
        ah.country_key,
        ah.lon,
        ah.lat,
        ah.location_tag,
        ah.area_display_name,
        ah.area_map_code,
        MIN(o.available_capacity_mw) FILTER (WHERE o.layer = 'planned') AS planned_available_capacity_mw,
        MIN(o.available_capacity_mw) FILTER (WHERE o.layer = 'forced') AS forced_available_capacity_mw,
        MIN(o.available_capacity_mw) AS combined_available_capacity_mw,
        COUNT(*) FILTER (WHERE o.layer = 'planned') AS planned_outage_count,
        COUNT(*) FILTER (WHERE o.layer = 'forced') AS forced_outage_count,
        string_agg(DISTINCT o.reason, '; ') FILTER (WHERE o.reason IS NOT NULL) AS reasons
    FROM asset_hours ah
    LEFT JOIN entsoe_availability_map.v_outage_event_latest o
        ON o.asset_code = ah.asset_code
       AND tstzrange(o.start_timeseries_utc, o.end_timeseries_utc, '[)')
           && tstzrange(ah.snapshot_utc, ah.snapshot_utc + interval '1 hour', '[)')
    GROUP BY
        ah.snapshot_utc,
        ah.asset_code,
        ah.asset_name,
        ah.asset_type,
        ah.production_type,
        ah.installed_capacity_mw,
        ah.country_key,
        ah.lon,
        ah.lat,
        ah.location_tag,
        ah.area_display_name,
        ah.area_map_code
),
layered AS (
    SELECT
        snapshot_utc,
        asset_code,
        asset_name,
        asset_type,
        production_type,
        installed_capacity_mw,
        country_key,
        lon,
        lat,
        location_tag,
        area_display_name,
        area_map_code,
        'planned'::text AS layer,
        planned_outage_count AS active_outage_count,
        COALESCE(planned_available_capacity_mw, installed_capacity_mw) AS available_capacity_mw,
        reasons
    FROM hourly_overlap

    UNION ALL

    SELECT
        snapshot_utc,
        asset_code,
        asset_name,
        asset_type,
        production_type,
        installed_capacity_mw,
        country_key,
        lon,
        lat,
        location_tag,
        area_display_name,
        area_map_code,
        'forced'::text AS layer,
        forced_outage_count AS active_outage_count,
        COALESCE(forced_available_capacity_mw, installed_capacity_mw) AS available_capacity_mw,
        reasons
    FROM hourly_overlap

    UNION ALL

    SELECT
        snapshot_utc,
        asset_code,
        asset_name,
        asset_type,
        production_type,
        installed_capacity_mw,
        country_key,
        lon,
        lat,
        location_tag,
        area_display_name,
        area_map_code,
        'combined'::text AS layer,
        planned_outage_count + forced_outage_count AS active_outage_count,
        COALESCE(combined_available_capacity_mw, installed_capacity_mw) AS available_capacity_mw,
        reasons
    FROM hourly_overlap
)
SELECT
    snapshot_utc,
    asset_code,
    asset_name,
    asset_type,
    production_type,
    country_key,
    lon,
    lat,
    location_tag,
    area_display_name,
    area_map_code,
    layer,
    active_outage_count,
    installed_capacity_mw,
    available_capacity_mw,
    GREATEST(COALESCE(installed_capacity_mw, 0) - COALESCE(available_capacity_mw, 0), 0) AS unavailable_capacity_mw,
    CASE
        WHEN installed_capacity_mw IS NULL OR installed_capacity_mw <= 0 THEN NULL
        ELSE available_capacity_mw / installed_capacity_mw
    END AS availability_ratio,
    CASE
        WHEN installed_capacity_mw IS NULL OR installed_capacity_mw <= 0 THEN 'unknown'
        WHEN available_capacity_mw <= 0 THEN 'red'
        WHEN available_capacity_mw < installed_capacity_mw - GREATEST(1.0, installed_capacity_mw * 0.01) THEN 'yellow'
        ELSE 'green'
    END AS status_color,
    reasons AS reason
FROM layered;

CREATE MATERIALIZED VIEW entsoe_availability_map.mv_availability_country_unknown_agg_next_24h AS
SELECT
    v.snapshot_utc,
    v.layer,
    v.country_key,
    c.country_name,
    c.lon,
    c.lat,
    COUNT(DISTINCT v.asset_code) AS asset_count,
    SUM(v.installed_capacity_mw) AS installed_capacity_mw,
    SUM(v.available_capacity_mw) AS available_capacity_mw,
    SUM(v.unavailable_capacity_mw) AS unavailable_capacity_mw,
    CASE
        WHEN SUM(v.installed_capacity_mw) IS NULL OR SUM(v.installed_capacity_mw) <= 0 THEN NULL
        ELSE SUM(v.available_capacity_mw) / SUM(v.installed_capacity_mw)
    END AS availability_ratio,
    CASE
        WHEN SUM(v.installed_capacity_mw) IS NULL OR SUM(v.installed_capacity_mw) <= 0 THEN 'unknown'
        WHEN SUM(v.available_capacity_mw) <= 0 THEN 'red'
        WHEN SUM(v.available_capacity_mw) < SUM(v.installed_capacity_mw) - GREATEST(1.0, SUM(v.installed_capacity_mw) * 0.01) THEN 'yellow'
        ELSE 'green'
    END AS status_color
FROM entsoe_availability_map.mv_availability_next_24h v
LEFT JOIN entsoe_availability_map.v_country_display_point c
    ON c.country_key = v.country_key
WHERE v.location_tag = 'unknown'
GROUP BY
    v.snapshot_utc,
    v.layer,
    v.country_key,
    c.country_name,
    c.lon,
    c.lat;

CREATE OR REPLACE VIEW entsoe_availability_map.v_availability_map_points_next_24h AS
SELECT
    snapshot_utc,
    layer,
    asset_code AS location_id,
    asset_name AS name,
    country_key AS country_name,
    lon,
    lat,
    status_color,
    location_tag,
    'plant'::text AS display_mode,
    1::bigint AS asset_count,
    installed_capacity_mw,
    available_capacity_mw,
    unavailable_capacity_mw,
    availability_ratio,
    active_outage_count,
    reason
FROM entsoe_availability_map.mv_availability_next_24h
WHERE location_tag = 'exact'

UNION ALL

SELECT
    snapshot_utc,
    layer,
    country_key AS location_id,
    COALESCE(country_name, country_key) || ' unknown assets' AS name,
    COALESCE(country_name, country_key) AS country_name,
    lon,
    lat,
    status_color,
    'unknown'::text AS location_tag,
    'country_centroid_aggregate'::text AS display_mode,
    asset_count,
    installed_capacity_mw,
    available_capacity_mw,
    unavailable_capacity_mw,
    availability_ratio,
    NULL::integer AS active_outage_count,
    'Aggregated unknown-location assets'::text AS reason
FROM entsoe_availability_map.mv_availability_country_unknown_agg_next_24h
WHERE lon IS NOT NULL
  AND lat IS NOT NULL;
