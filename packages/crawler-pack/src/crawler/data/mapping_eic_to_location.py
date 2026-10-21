import json
import os
import re

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.types import Float, String

# ================= Configuration (Defaults) =================
DEFAULT_DB_URI = "postgresql://opendata:opendata@localhost:6432/opendata"
DEFAULT_SOURCE_SCHEMA = "power_system_data"
DEFAULT_SOURCE_TABLE = "powersystemdata"
DEFAULT_TARGET_TABLE = "eic_geo_location"
DEFAULT_MAPPING_FILE = os.path.join(os.path.dirname(__file__), "mapping_p_to_g.json")
# ===========================================================


def extract_from_project_id(text_val):
    """
    Parses complex structures in the project_id column.
    Goal: Find codes within 'ENTSOE': {'CODE1', 'CODE2'}.
    """
    if not isinstance(text_val, str):
        return []

    # 1. Locate 'ENTSOE' and the following set content
    # Look for { ... } immediately following 'ENTSOE':
    entsoe_match = re.search(r"'ENTSOE':\s*\{([^}]+)\}", text_val)

    if not entsoe_match:
        return []

    content_inside = entsoe_match.group(1)

    # 2. Extract specific codes (content wrapped in single quotes)
    codes = re.findall(r"'([^']+)'", content_inside)

    # Filter out potential 'nan' strings
    return [c for c in codes if c.lower() != "nan"]


def extract_simple_eic(text_val):
    """
    Parses old eic_code column (handles {'CODE'} format)
    """
    if not isinstance(text_val, str):
        return []
    codes = re.findall(r"'([^']+)'", text_val)
    return [c for c in codes if c.lower() != "nan"]


def etl_run(
    engine=None,
    source_schema=DEFAULT_SOURCE_SCHEMA,
    source_table=DEFAULT_SOURCE_TABLE,
    target_table=DEFAULT_TARGET_TABLE,
    mapping_file=DEFAULT_MAPPING_FILE,
):
    """
    Performs the ETL process for EIC to geographic location mapping.
    """
    if engine is None:
        engine = create_engine(DEFAULT_DB_URI)

    print(f"1. Reading data from database ({source_schema}.{source_table})...")

    # Query: Read project_id and eic_code, filtering for ENTSOE relevant rows
    query = f"""
    SELECT project_id, eic_code, lat, lon
    FROM {source_schema}.{source_table}
    WHERE project_id LIKE '%%ENTSOE%%'
       OR eic_code LIKE '%%''%%'
    """

    try:
        df = pd.read_sql(query, engine)
        print(f"-> Successfully read {len(df)} potential records.")
    except Exception as e:
        print(f"SQL Read failed: {e}")
        return

    # Load mapping file
    try:
        with open(mapping_file, encoding="utf-8") as f:
            p_to_g_map = json.load(f)
        print(f"-> Mapping file loaded successfully: {mapping_file}")
    except Exception as e:
        print(
            f"Warning: Could not load mapping file {mapping_file} ({e}), only parent codes will be processed."
        )
        p_to_g_map = {}

    result_rows = []
    stats = {"from_project_id": 0, "from_eic_col": 0, "mapped_children": 0}

    print("2. Starting parsing...")

    for _, row in df.iterrows():
        # Check coordinates
        if pd.isna(row["lat"]) or pd.isna(row["lon"]):
            continue

        geo = {"lat": float(row["lat"]), "lon": float(row["lon"])}
        found_codes = set()  # Dedup using set

        # Strategy A: Extract from project_id (Primary source)
        pid_codes = extract_from_project_id(row["project_id"])
        if pid_codes:
            found_codes.update(pid_codes)
            stats["from_project_id"] += len(pid_codes)

        # Strategy B: Extract from eic_code column (Legacy fallback)
        eic_col_codes = extract_simple_eic(row["eic_code"])
        if eic_col_codes:
            found_codes.update(eic_col_codes)
            stats["from_eic_col"] += len(eic_col_codes)

        if not found_codes:
            continue

        # Process each extracted code
        for code in found_codes:
            # Entry for the code itself
            result_rows.append({"eic_code": code, **geo})

            # Map child units if available
            if code in p_to_g_map:
                for child in p_to_g_map[code]:
                    result_rows.append({"eic_code": child, **geo})
                    stats["mapped_children"] += 1

    # Display statistics
    print("-" * 40)
    print(f"Codes extracted from project_id: {stats['from_project_id']}")
    print(f"Codes extracted from eic_code: {stats['from_eic_col']}")
    print(f"Mapped child units: {stats['mapped_children']}")
    print("-" * 40)

    # Write to database
    df_final = pd.DataFrame(result_rows)
    if not df_final.empty:
        # Final deduplication
        df_final.drop_duplicates(subset=["eic_code"], inplace=True)
        print(
            f"Preparing to write {len(df_final)} unique records to {source_schema}.{target_table}..."
        )

        df_final.to_sql(
            target_table,
            engine,
            schema=source_schema,
            if_exists="replace",
            index=False,
            dtype={"eic_code": String(30), "lat": Float(), "lon": Float()},
        )

        # Create Index
        with engine.begin() as conn:
            # Fix: index name and table name updated to use dynamic parameters correctly
            index_name = f"idx_{target_table}_eic"
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {source_schema}.{target_table} (eic_code)"
                )
            )

        print("Write successful!")
    else:
        print("No valid data generated. Check regex/parsing logic.")


if __name__ == "__main__":
    etl_run()
