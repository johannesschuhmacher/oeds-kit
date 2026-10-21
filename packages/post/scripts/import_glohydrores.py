"""Import the GloHydroRes CSV into the OEDS Postgres database.

This loader creates a dedicated schema and a cleaned dashboard view that can
be queried directly from Grafana.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg2


DEFAULT_CSV = r"\\iipsrv-file1.iip.kit.edu\synergie\Data\GloHydroRes\GloHydroRes_vs1.csv"


DDL_SQL = """
CREATE SCHEMA IF NOT EXISTS glohydrores;

CREATE TABLE IF NOT EXISTS glohydrores.plants_raw (
    id text PRIMARY KEY,
    country text,
    name text,
    capacity_mw double precision,
    plant_lat double precision,
    plant_lon double precision,
    plant_type text,
    plant_type_source text,
    commissioning_year integer,
    plant_source text,
    plant_source_id text,
    dam_name text,
    dam_height_m double precision,
    dam_height_source text,
    reservoir_name text,
    reservoir_source text,
    reservoir_source_id text,
    manual_dam_lat double precision,
    manual_dam_lon double precision,
    river text,
    head_m double precision,
    head_source text,
    reservoir_avg_depth_m double precision,
    reservoir_area_km2 double precision,
    reservoir_volume_km3 double precision,
    reservoir_attr_source text,
    reservoir_attr_id text,
    hydrolakes_id text,
    final_comments text,
    source_path text,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS plants_raw_country_idx
    ON glohydrores.plants_raw (country);

CREATE INDEX IF NOT EXISTS plants_raw_type_idx
    ON glohydrores.plants_raw (plant_type);

CREATE INDEX IF NOT EXISTS plants_raw_capacity_idx
    ON glohydrores.plants_raw (capacity_mw DESC);

GRANT USAGE ON SCHEMA glohydrores TO readonly;
GRANT SELECT ON glohydrores.plants_raw TO readonly;
"""


COPY_SQL = """
COPY glohydrores.plants_raw (
    id,
    country,
    name,
    capacity_mw,
    plant_lat,
    plant_lon,
    plant_type,
    plant_type_source,
    commissioning_year,
    plant_source,
    plant_source_id,
    dam_name,
    dam_height_m,
    dam_height_source,
    reservoir_name,
    reservoir_source,
    reservoir_source_id,
    manual_dam_lat,
    manual_dam_lon,
    river,
    head_m,
    head_source,
    reservoir_avg_depth_m,
    reservoir_area_km2,
    reservoir_volume_km3,
    reservoir_attr_source,
    reservoir_attr_id,
    hydrolakes_id,
    final_comments
)
FROM STDIN WITH (
    FORMAT CSV,
    HEADER TRUE,
    NULL '',
    ENCODING 'UTF8'
)
"""


VIEW_SQL = """
CREATE OR REPLACE VIEW glohydrores.plants_dashboard AS
SELECT
    id,
    country,
    name AS plant_name,
    capacity_mw,
    COALESCE(NULLIF(BTRIM(plant_type), ''), 'Unknown') AS plant_type_code,
    CASE COALESCE(NULLIF(BTRIM(plant_type), ''), 'Unknown')
        WHEN 'ROR' THEN 'Run-of-river'
        WHEN 'STO' THEN 'Storage'
        WHEN 'PS' THEN 'Pumped storage'
        WHEN 'Canal' THEN 'Canal'
        ELSE 'Unknown'
    END AS plant_type,
    plant_type_source,
    CASE
        WHEN commissioning_year BETWEEN 1800 AND EXTRACT(YEAR FROM CURRENT_DATE)::int
        THEN commissioning_year
        ELSE NULL
    END AS commissioning_year,
    CASE
        WHEN commissioning_year BETWEEN 1800 AND EXTRACT(YEAR FROM CURRENT_DATE)::int
        THEN (commissioning_year / 10) * 10
        ELSE NULL
    END AS commissioning_decade,
    plant_source,
    plant_source_id,
    NULLIF(BTRIM(dam_name), '') AS dam_name,
    CASE WHEN dam_height_m >= 0 THEN dam_height_m END AS dam_height_m,
    dam_height_source,
    COALESCE(NULLIF(BTRIM(reservoir_name), ''), NULLIF(BTRIM(dam_name), '')) AS reservoir_name,
    NULLIF(BTRIM(reservoir_source), '') AS reservoir_source,
    NULLIF(BTRIM(reservoir_source_id), '') AS reservoir_source_id,
    manual_dam_lat,
    manual_dam_lon,
    NULLIF(BTRIM(river), '') AS river,
    CASE WHEN head_m >= 0 THEN head_m END AS head_m,
    head_source,
    CASE WHEN reservoir_avg_depth_m >= 0 THEN reservoir_avg_depth_m END AS reservoir_avg_depth_m,
    CASE WHEN reservoir_area_km2 >= 0 THEN reservoir_area_km2 END AS reservoir_area_km2,
    CASE WHEN reservoir_volume_km3 >= 0 THEN reservoir_volume_km3 END AS reservoir_volume_km3,
    NULLIF(BTRIM(reservoir_attr_source), '') AS reservoir_attr_source,
    NULLIF(BTRIM(reservoir_attr_id), '') AS reservoir_attr_id,
    NULLIF(BTRIM(hydrolakes_id), '') AS hydrolakes_id,
    NULLIF(BTRIM(final_comments), '') AS final_comments,
    plant_lat,
    plant_lon,
    COALESCE(plant_lat, manual_dam_lat) AS map_lat,
    COALESCE(plant_lon, manual_dam_lon) AS map_lon,
    CASE
        WHEN plant_lat IS NOT NULL AND plant_lon IS NOT NULL THEN 'Plant'
        WHEN manual_dam_lat IS NOT NULL AND manual_dam_lon IS NOT NULL THEN 'Dam'
        ELSE 'Missing'
    END AS coordinate_source,
    source_path,
    imported_at
FROM glohydrores.plants_raw;

GRANT SELECT ON glohydrores.plants_dashboard TO readonly;
"""


SUMMARY_SQL = """
SELECT
    COUNT(*) AS plants,
    ROUND(SUM(capacity_mw)::numeric, 1) AS total_capacity_mw,
    COUNT(DISTINCT country) AS countries,
    COUNT(*) FILTER (WHERE reservoir_name IS NOT NULL) AS plants_with_reservoir_name
FROM glohydrores.plants_dashboard
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-path", default=DEFAULT_CSV, help="Path to GloHydroRes CSV")
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--db-port", type=int, default=6432)
    parser.add_argument("--db-name", default="opendata")
    parser.add_argument("--db-user", default="opendata")
    parser.add_argument("--db-password", default="opendata")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    conn = psycopg2.connect(
        host=args.db_host,
        port=args.db_port,
        dbname=args.db_name,
        user=args.db_user,
        password=args.db_password,
    )

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL_SQL)
                cur.execute("ALTER TABLE glohydrores.plants_raw ALTER COLUMN source_path DROP NOT NULL")
                cur.execute("TRUNCATE TABLE glohydrores.plants_raw")
                with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    cur.copy_expert(COPY_SQL, handle)
                cur.execute(
                    "UPDATE glohydrores.plants_raw "
                    "SET source_path = %s, imported_at = now()",
                    (str(csv_path),),
                )
                cur.execute(VIEW_SQL)
                cur.execute("ANALYZE glohydrores.plants_raw")
                cur.execute(SUMMARY_SQL)
                plants, total_capacity_mw, countries, plants_with_reservoir_name = cur.fetchone()

        print(f"Imported {plants} plants into glohydrores.plants_raw")
        print(f"Total capacity: {total_capacity_mw} MW across {countries} countries")
        print(f"Plants with named reservoir link: {plants_with_reservoir_name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
