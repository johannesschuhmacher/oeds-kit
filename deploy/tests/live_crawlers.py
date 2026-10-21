"""Bounded live-source checks in disposable Docker containers and separate databases.

Run on the test VM, never against the operational database. Nonempty tables are
evidence of ingestion, not proof that every dataset or historical year works.
"""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
import inspect
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

DB_HOST = "oeds-crawler-validation-db"
NETWORK = "oeds-crawler-validation"
ROOT = Path(__file__).resolve().parent
IMAGE = "oeds-test:runtime"
BOOTSTRAP_LOCK = threading.Lock()
SOURCES = {
    "kit": Path("/app/modular_repos/modules/oeds-crawler-pack/src/crawler"),
    "core": Path("/app/modular_repos/sources/oeds-core/oeds/crawler"),
}
REQUIRED_TABLES = {
    "kit:copernicus_cds": ("downloaded_files", "variable_statistics"),
    "kit:entsoe_api": ("day_ahead_prices", "load_forecasts", "wind_solar_forecasts"),
    "kit:entsoe_fms": ("EnergyPrices", "ActualTotalLoad"),
    "kit:epex_spot": ("continuous_statistics", "continuous_indices", "continuous_trades", "intraday_auction_prices_volumes"),
    "kit:regelleistung": ("file_rows", "numeric_values"),
    "kit:smard": ("prices", "smard"),
    "kit:weather_forecast": ("hourly_forecast",),
    "kit:mastr": ("EinheitenWind", "Katalogkategorien", "Katalogwerte"),
    "kit:power_system_data": ("powersystemdata", "eic_geo_location"),
    "core:entsoe_crawler": ("query_day_ahead_prices", "query_load", "query_load_forecast",
                             "query_generation_forecast", "query_generation", "query_wind_and_solar_forecast"),
    "core:regelleistung": ("fcr_bedarfe", "fcr_ergebnisse", "fcr_anonyme_ergebnisse"),
}
for _source in ("kit", "core"):
    REQUIRED_TABLES[f"{_source}:ninja"] = ("capacity_solar_merra2", "capacity_wind_on", "capacity_wind_off")
    REQUIRED_TABLES[f"{_source}:entsog"] = ("physical_flow", "allocation", "firm_technical")


def inventory():
    from oeds_scheduler_ui.discovery import discover_crawler_specs
    result = {}
    for source, path in SOURCES.items():
        prefix = "crawler" if source == "kit" else "oeds.crawler"
        discovered = discover_crawler_specs(source_name=source, source_path=path.parent,
                                             crawler_package_path=path, module_prefix=prefix)
        for name in discovered.crawlers:
            result[f"{source}:{name}"] = str(path / f"{name}.py")
    return result


def database_uri(case):
    return f"postgresql://opendata:opendata@{DB_HOST}:5432/" + case.replace(":", "_")


def execute_case(case):
    import pandas as pd
    import yaml
    from dotenv import load_dotenv

    load_dotenv("/validation/.env", override=False)
    for key in list(os.environ):
        if "EMAIL" in key:
            os.environ.pop(key)
    os.environ.update(OEDS_DB_HOST=DB_HOST, OEDS_DB_PORT="5432",
                      OEDS_DB_PASSWORD="opendata", OEDS_CRAWLER_DATA_DIR="/work/data")
    uri = database_uri(case)
    os.environ.update(EPEX_DATABASE_URI=uri, OEDS_EPEX_DATABASE_URI=uri)
    for target, original in [("ENTSOE_API_KEY", "ENTSOE_API"),
                             ("CDSAPI_URL", "COPERNICUS_CDS_URL"),
                             ("CDSAPI_KEY", "COPERNICUS_CDS_KEY")]:
        if os.environ.get(original):
            os.environ[target] = os.environ[original]
    source, name = case.split(":")
    settings = yaml.safe_load(Path("/app/CRAWLER_CONFIG.yml").read_text())
    config = {**settings["default"], **settings.get(name, {})}
    begin = pd.Timestamp(datetime.now(timezone.utc).date() - timedelta(days=3), tz="UTC")
    end = begin + pd.Timedelta(days=1)
    config.update(database_uri=uri + "?options=--search_path=", db_uri=uri,
                  schema_name="public" if name == "nuts_mapper" else name,
                  default_start_date=begin.date().isoformat(), start_date=begin.date().isoformat(),
                  lookback_days=3, lookahead_days=1, update_interval_days=1,
                  request_timeout_seconds=45, forecast_days=1, forecast_hours=24, past_hours=0,
                  months=[1], start_year=2024, end_year=2024, max_files_per_run=3,
                  entsoe_api_key=os.environ.get("ENTSOE_API", ""),
                  gie_api_key=os.environ.get("GIE_API_KEY", ""),
                  ipnt_client_id=os.environ.get("NETZTRANSPARENZ_CLIENT_ID", ""),
                  ipnt_client_secret=os.environ.get("NETZTRANSPARENZ_CLIENT_SECRET", ""),
                  jao_api_key=os.environ.get("JAO_API_KEY", ""))
    config["email"] = {"mailhost": "", "fromaddr": "", "toaddrs": [],
                       "subject": "", "username": "", "password": ""}
    if name == "entsoe_fms":
        config.update(target_data_items=["EnergyPrices_12.1.D_r3", "ActualTotalLoad_6.1.A_r3"],
                      fms_package_window_months=1, fms_package_write_mode="full_upsert")
    if name == "osm_power":
        config.update(bbox=[49.0, 8.35, 49.05, 8.45], max_elements=100)
    if source == "kit" and name == "mastr":
        config.update(tables=["EinheitenWind", "Katalogkategorien", "Katalogwerte"], max_rows_per_table=100)
    if source == "core":
        config.update(max_rows=48, max_profiles=2, max_houses=1, max_buildings=1, max_files=1)
        if name == "jrc_idees":
            config["countries"] = ["DE"]
        if name == "frequency":
            config.update(start_year=2011, end_year=2011)
        if name == "regelleistung":
            config["tables"] = ["fcr_bedarfe", "fcr_ergebnisse", "fcr_anonyme_ergebnisse"]
    if name == "regelleistung":
        config["lookback_days"] = 35  # The file archive publishes completed months.
    if name == "epex_spot":
        config["start_date"] = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    if name == "copernicus_cds":
        config.update(dataset="reanalysis-era5-single-levels", request={
            "product_type": ["reanalysis"], "variable": ["2m_temperature"],
            "year": ["2025"], "month": ["01"], "day": ["01"], "time": ["12:00"],
            "area": [49.5, 8.0, 49.0, 8.5], "data_format": "netcdf"})
    module = importlib.import_module(("crawler." if source == "kit" else "oeds.crawler.") + name)
    tree = ast.parse((SOURCES[source] / (name + ".py")).read_text())
    candidates = [node.name for node in tree.body if isinstance(node, ast.ClassDef)
                  and any(isinstance(base, ast.Name) and base.id in
                          {"BaseCrawler", "ContinuousCrawler", "DownloadOnceCrawler"}
                          for base in node.bases)]
    cls = getattr(module, candidates[0])
    if name == "open_meteo":
        config["locations"] = module.DEFAULT_LOCATIONS[:1]
    elif name == "weather_forecast":
        config["locations"] = cls.DEFAULT_LOCATIONS[:1]
    if source == "core" and name == "eon_grid_fees":
        from oeds.crawler.nuts_mapper import NutsCrawler
        NutsCrawler("public", config).crawl_structural()
    if source == "core" and name == "eex" and "config" not in inspect.signature(cls).parameters:
        crawler = cls(config["schema_name"])
    else:
        crawler = cls(config["schema_name"], config) if source == "core" else cls(name, config)
    if source == "kit":
        crawler.run()
    elif name == "entsog":
        crawler.pullData(["connectionpoints", "operators", "balancingzones", "operatorpointdirections"])
        crawler.pullOperationalData(["Physical Flow", "Allocation", "Firm Technical"], begin.date(), end.date())
    elif name == "entsoe_crawler":
        crawler.init_base_sql()
        for method in ["query_day_ahead_prices", "query_load", "query_load_forecast",
                       "query_generation_forecast", "query_wind_and_solar_forecast", "query_generation"]:
            crawler.download_entsoe(["DE_LU"], getattr(crawler.client, method), begin, begin + pd.Timedelta(days=2))
    elif name == "regelleistung":
        crawler.crawl_temporal(begin.date(), end.date())
    elif name in {"netztransparenz", "eview"}:
        crawler.crawl_temporal(begin.tz_localize(None).to_pydatetime(), end.tz_localize(None).to_pydatetime())
    elif hasattr(crawler, "crawl_from_to"):
        if name == "e2watch":
            crawler.crawl_structural()
        crawler.crawl_from_to(begin.tz_localize(None).to_pydatetime(), end.tz_localize(None).to_pydatetime())
    else:
        crawler.crawl_structural(recreate=True)


def inspect_database(case):
    from sqlalchemy import create_engine, text
    engine = create_engine(database_uri(case), connect_args={"options": "-c statement_timeout=15000"})
    result = {}
    with engine.connect() as conn:
        tables = conn.execute(text("""SELECT schemaname, tablename FROM pg_tables
            WHERE schemaname NOT LIKE 'pg_%' AND schemaname NOT LIKE '\\_%'
            AND schemaname != 'information_schema'
            AND tablename NOT IN ('metadata', 'spatial_ref_sys') ORDER BY 1, 2""")).all()
        for schema, table in tables:
            quoted = engine.dialect.identifier_preparer
            table_sql = quoted.quote_schema(schema) + "." + quoted.quote(table)
            result[f"{schema}.{table}"] = conn.execute(text(f"SELECT count(*) FROM {table_sql}")).scalar()
        if case == "kit:gie_agsi_alsi" and result.get("gie_agsi_alsi.daily_inventory"):
            assert conn.execute(text("""SELECT count(*) FROM gie_agsi_alsi.daily_inventory
                WHERE platform='alsi' AND lng_inventory_gwh IS NOT NULL
                AND lng_inventory_thousand_m3 IS NOT NULL AND lng_send_out_gwh_per_day IS NOT NULL
            """)).scalar() > 0, "ALSI rows have no normalized LNG values"
        if case == "kit:smard" and result.get("smard.smard"):
            assert conn.execute(text("""SELECT count(*) FROM public.metadata m WHERE m.schema_name='smard'
                AND m.temporal_start=(SELECT min(t) FROM (
                    SELECT min(timestamp) t FROM smard.smard UNION ALL SELECT min(timestamp) FROM smard.prices) s)
                AND m.temporal_end=(SELECT max(t) FROM (
                    SELECT max(timestamp) t FROM smard.smard UNION ALL SELECT max(timestamp) FROM smard.prices) s)
            """)).scalar() == 1, "SMARD metadata does not match stored coverage"
    print(json.dumps(result), flush=True)


def docker_command(*args):
    return ["docker", "run", "--rm", "--network", NETWORK, "--user", os.environ.get("OEDS_LIVE_USER", "1000:1000"),
            "--memory", os.environ.get("OEDS_LIVE_MEMORY", "2g"), "--cpus", os.environ.get("OEDS_LIVE_CPUS", "1"), "--workdir", "/work",
            "--tmpfs", "/work:rw,size=2g,mode=1777", "-v", f"{ROOT}:/validation:ro,z",
            "--entrypoint", "python", IMAGE, "/validation/live_crawlers.py", *args]


def run_case(case, secrets, timeout, reset=False):
    started = time.monotonic()
    dbname = case.replace(":", "_")
    # The shared readonly role in the real init SQL cannot be updated concurrently.
    with BOOTSTRAP_LOCK:
        if reset:
            subprocess.run(["docker", "exec", DB_HOST, "dropdb", "-U", "opendata",
                            "--if-exists", "--force", dbname], check=True, capture_output=True)
        exists = subprocess.check_output(["docker", "exec", DB_HOST, "psql", "-U", "opendata", "-d", "postgres",
                        "-Atc", f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'"], text=True).strip()
        if not exists:
            subprocess.run(["docker", "exec", DB_HOST, "psql", "-U", "opendata", "-d", "postgres",
                            "-v", "ON_ERROR_STOP=1", "-c", f'CREATE DATABASE "{dbname}" TEMPLATE template0'],
                           check=True, capture_output=True)
            subprocess.run(["docker", "exec", DB_HOST, "psql", "-U", "opendata", "-d", dbname,
                            "-v", "ON_ERROR_STOP=1", "-c", "CREATE EXTENSION timescaledb",
                            "-f", "/docker-entrypoint-initdb.d/10-init.sql"], check=True, capture_output=True)
    container = "crawler-check-" + dbname.replace("_", "-")
    command = docker_command("--worker", case)
    command[2:2] = ["--name", container]
    print(f"START {case} (limit {timeout}s)", flush=True)
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=timeout, text=True, errors="replace")
        output, returncode = completed.stdout, completed.returncode
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=True)
        output = exc.stdout or b""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        returncode = 124
    for secret in secrets:
        output = output.replace(secret, "[REDACTED]")
    (ROOT / "logs" / (dbname + ".log")).write_text(output)
    inspected = subprocess.run(docker_command("--inspect", case), capture_output=True, text=True, timeout=90)
    tables = json.loads(inspected.stdout) if inspected.returncode == 0 else {}
    data_tables = {name: rows for name, rows in tables.items() if rows and
                   name.rsplit(".", 1)[-1] not in {"access_status", "requests", "locations", "psrtype", "areas"}}
    if case == "core:entsoe_crawler":
        data_tables = {name: rows for name, rows in data_tables.items() if ".query_" in name}
    elif case == "core:e2watch":
        data_tables = {name: rows for name, rows in data_tables.items() if name.endswith(".e2watch")}
    status = "data_loaded" if data_tables and returncode == 0 else "failed"
    if returncode == 124:
        status = "timeout_partial" if data_tables else "timeout"
    elif returncode == 137:
        status = "memory_limit"
    elif returncode == 0 and ("ERROR" in output or "Traceback" in output):
        status = "partial" if data_tables else "no_data"
    elif returncode == 0 and not data_tables:
        status = "no_data"
    if status == "data_loaded":
        schema = case.split(":")[1]
        if any(not tables.get(f"{schema}.{name}") for name in REQUIRED_TABLES.get(case, ())):
            status = "partial"
    if inspected.returncode:
        status = "inspection_failed"
        with (ROOT / "logs" / (dbname + ".log")).open("a") as log:
            log.write("\nDatabase inspection failed:\n" + inspected.stderr)
    result = {"case": case, "status": status, "exit_code": returncode,
              "seconds": round(time.monotonic() - started), "tables": tables,
              "user": os.environ.get("OEDS_LIVE_USER", "1000:1000"), "image": IMAGE}
    (ROOT / "logs" / (dbname + ".json")).write_text(json.dumps(result, indent=2))
    print(json.dumps({**result, "tables": len(tables), "rows": sum(tables.values())}), flush=True)
    return result


def main():
    global IMAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--inspect")
    parser.add_argument("--source", choices=["core", "kit", "all"], default="all")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--reset", action="store_true", help="Drop selected validation databases before retrying")
    parser.add_argument("--memory", default="2g", help="Memory limit per worker container")
    parser.add_argument("--cpus", default="1", help="CPU limit per worker container")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--user", default="1000:1000", help="Container UID:GID, matching the normal runtime by default")
    args = parser.parse_args()
    IMAGE = args.image
    if args.list:
        print(json.dumps(inventory()))
    elif args.worker:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
        try:
            execute_case(args.worker)
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    elif args.inspect:
        inspect_database(args.inspect)
    else:
        os.umask(0o077)
        os.environ["OEDS_LIVE_MEMORY"] = args.memory
        os.environ["OEDS_LIVE_CPUS"] = args.cpus
        os.environ["OEDS_LIVE_USER"] = args.user
        (ROOT / "logs").mkdir(exist_ok=True)
        cases = json.loads(subprocess.check_output(docker_command("--list"), text=True))
        if args.cases and set(args.cases) - cases.keys():
            parser.error("Unknown crawlers: " + ", ".join(sorted(set(args.cases) - cases.keys())))
        cases = [case for case in cases if (args.source == "all" or case.startswith(args.source + ":"))
                 and (not args.cases or case in args.cases)]
        # The private env file is mounted only for workers; never print its contents.
        secrets = [line.partition("=")[2].strip().strip('\"\'')
                   for line in (ROOT / ".env").read_text().splitlines()
                   if "=" in line and not line.lstrip().startswith("#")]
        secrets = sorted((value for value in secrets if len(value) >= 4), key=len, reverse=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda case: run_case(case, secrets, args.timeout, args.reset), cases))
        print("SUMMARY " + json.dumps({status: sum(item["status"] == status for item in results)
                                       for status in sorted({item["status"] for item in results})}), flush=True)
        if any(item["status"] != "data_loaded" for item in results):
            sys.exit(1)


if __name__ == "__main__":
    main()
