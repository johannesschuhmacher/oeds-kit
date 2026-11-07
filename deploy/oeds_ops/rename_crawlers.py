"""Move an installation from the crawler names before release 1.5.0 to the new ones.

    python rename_crawlers.py /app/CRAWLER_CONFIG.yml

Runs in the scheduler image (ruamel.yaml, SQLAlchemy and the crawler pack are
installed there) while the scheduler and the admin interface are stopped. Every
step only acts on what still has an old name, so a second run changes nothing.

- Database: renames the schemas (and the powerplantmatching table), the rows of
  public.metadata and the schema and job names recorded by gap filling.
- Configuration: renames the crawler sections, their schema names and every
  string that names an old crawler, schema or command. A weather_forecast
  section is removed; if it was enabled, open_meteo is enabled instead.
"""

import sys
from pathlib import Path

from ruamel.yaml import YAML
from sqlalchemy import create_engine, text

from crawler.common.runtime_env import resolve_database_uri

CRAWLERS = {
    "entsoe_fms": "entsoe_files",
    "ninja": "renewables_ninja",
    "power_system_data": "powerplantmatching",
    "energy_forecast_crawler": "energyforecast",
    "eurostat_crawler": "eurostat",
}
SCHEMAS = {
    "entsoe_fms": "entsoe_files",
    "entsoe_fms_gapfilled": "entsoe_files_gapfilled",
    "ninja": "renewables_ninja",
    "power_system_data": "powerplantmatching",
    "energy_forecast": "energyforecast",
}
# Old -> new in configuration strings (gap-filling schemas, post-run commands, tables).
STRINGS = {
    "entsoe_fms": "entsoe_files",
    "entsoe-fms": "entsoe-files",
    "power_system_data": "powerplantmatching",
    "powersystemdata": "powerplants",
}


def rename_database(engine) -> None:
    with engine.begin() as conn:
        existing = set(conn.execute(text("SELECT nspname FROM pg_namespace")).scalars())
        for old, new in SCHEMAS.items():
            if old in existing and new not in existing:
                conn.execute(text(f'ALTER SCHEMA "{old}" RENAME TO "{new}"'))
                print(f"schema {old} -> {new}")
        if conn.execute(text("SELECT to_regclass('powerplantmatching.powersystemdata')")).scalar():
            conn.execute(text("ALTER TABLE powerplantmatching.powersystemdata RENAME TO powerplants"))
            print("table powerplantmatching.powersystemdata -> powerplants")
        if conn.execute(text("SELECT to_regclass('public.metadata')")).scalar():
            for old, new in SCHEMAS.items():
                conn.execute(
                    text(
                        "UPDATE public.metadata SET schema_name = :new WHERE schema_name = :old "
                        "AND NOT EXISTS (SELECT 1 FROM public.metadata WHERE schema_name = :new)"
                    ),
                    {"old": old, "new": new},
                )
        # Gap filling records job and schema names; gapfill_tracking is keyed by them.
        columns = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'entsoe_files_gapfilled' AND table_name LIKE 'gapfill%' "
                "AND column_name IN ('job_name', 'source_schema', 'target_schema')"
            )
        ).all()
        for table, column in columns:
            for old, new in SCHEMAS.items():
                conn.execute(
                    text(f'UPDATE entsoe_files_gapfilled."{table}" SET "{column}" = :new WHERE "{column}" = :old'),
                    {"old": old, "new": new},
                )


def replace_strings(node):
    if isinstance(node, str):
        for old, new in STRINGS.items():
            node = node.replace(old, new)
        return node
    if isinstance(node, dict):
        for key in node:
            node[key] = replace_strings(node[key])
    elif isinstance(node, list):
        for index, item in enumerate(node):
            node[index] = replace_strings(item)
    return node


def rename_config(path: Path) -> bool:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # keep long lines as they are
    # write empty values as null, as the template does
    yaml.representer.add_representer(type(None), lambda rep, _: rep.represent_scalar("tag:yaml.org,2002:null", "null"))
    config = yaml.load(path.read_text(encoding="utf-8"))
    before = path.read_text(encoding="utf-8")

    for old, new in CRAWLERS.items():
        if old in config and new not in config:
            config.insert(list(config).index(old), new, config.pop(old))
            print(f"config section {old} -> {new}")
    for section in config.values():
        if isinstance(section, dict) and section.get("schema_name") in SCHEMAS:
            section["schema_name"] = SCHEMAS[section["schema_name"]]
    replace_strings(config)

    weather = config.pop("weather_forecast", None)
    if weather is not None:
        print("config section weather_forecast removed (now open_meteo)")
        if weather.get("enable") and isinstance(config.get("open_meteo"), dict):
            config["open_meteo"]["enable"] = True
            print("open_meteo enabled, as weather_forecast was")
    if isinstance(config.get("open_meteo"), dict):
        for key in ("forecast_days", "past_days"):
            config["open_meteo"].pop(key, None)

    with path.open("w", encoding="utf-8", newline="") as handle:
        yaml.dump(config, handle)
    return path.read_text(encoding="utf-8") != before


def main() -> None:
    path = Path(sys.argv[1])
    config = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    engine = create_engine(resolve_database_uri(config["default"]["database_uri"]))
    rename_database(engine)
    print("configuration changed" if rename_config(path) else "configuration already up to date")


if __name__ == "__main__":
    main()
