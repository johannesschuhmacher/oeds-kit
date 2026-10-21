# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
from pathlib import Path
import sys

import yaml
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "scripts" / "lib" / "entsoe_availability_map.sql"
CONFIG_FILE = Path(
    os.getenv("OEDS_CRAWLER_CONFIG", ROOT / "CRAWLER_CONFIG.yml")
).expanduser()
REQUIRED_SOURCE_TABLES = (
    ("entsoe_fms", "powersystemdata"),
    ("entsoe_fms", "UnavailabilityOfProductionAndGenerationUnits"),
    ("entsoe_fms", "InstalledGenerationCapacityPerProductionUnit"),
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oeds_post_scripts.runtime_env import resolve_database_uri


def load_database_uri() -> str:
    with CONFIG_FILE.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    default_uri = config["default"]["database_uri"]
    crawler_uri = config.get("entsoe_fms", {}).get("database_uri", default_uri)
    return f"{resolve_database_uri(crawler_uri)}entsoe_fms"


def find_missing_source_tables(engine) -> list[str]:
    missing = []
    statement = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema_name
              AND table_name = :table_name
        )
        """
    )
    with engine.begin() as conn:
        for schema_name, table_name in REQUIRED_SOURCE_TABLES:
            exists = conn.execute(
                statement,
                {"schema_name": schema_name, "table_name": table_name},
            ).scalar()
            if not exists:
                missing.append(f'{schema_name}."{table_name}"')
    return missing


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    sql = SQL_FILE.read_text(encoding="utf-8")
    engine = create_engine(load_database_uri())
    missing_tables = find_missing_source_tables(engine)
    if missing_tables:
        logging.warning(
            "Skipping ENTSO-E availability map refresh because required source "
            "tables are missing: %s",
            ", ".join(missing_tables),
        )
        return

    logging.info("Refreshing ENTSO-E availability map objects...")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    logging.info("ENTSO-E availability map objects refreshed.")


if __name__ == "__main__":
    main()
