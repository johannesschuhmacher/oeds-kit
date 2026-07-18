#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS=1800
INCLUDE_ENTSOE_FMS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout-seconds) TIMEOUT_SECONDS=$2; shift 2 ;;
    --include-entsoe-fms) INCLUDE_ENTSOE_FMS=true; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOYMENT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd -- "$DEPLOYMENT_ROOT/../../.." && pwd)
source "$SCRIPT_DIR/smoke_lib.sh"

cd "$DEPLOYMENT_ROOT"
export COMPOSE_PROJECT_NAME=oeds-modular-test
COMPOSE=(docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml)
RUNTIME_DIR=.tmp/runtime-active-crawlers
RUNTIME_ROOT=$DEPLOYMENT_ROOT/$RUNTIME_DIR

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT

cleanup
mkdir -p "$RUNTIME_ROOT/crawler/data" "$RUNTIME_ROOT/logs"
SOURCE_ENV=${OEDS_CRAWLER_ENV_FILE:-}
if [[ -z "$SOURCE_ENV" && -f "$REPO_ROOT/crawler/.env" ]]; then
  SOURCE_ENV=$REPO_ROOT/crawler/.env
fi
if [[ -z "$SOURCE_ENV" && -f "$DEPLOYMENT_ROOT/.env" ]]; then
  RUNTIME_FROM_COMPOSE_ENV=$(grep -E '^OEDS_RUNTIME_DIR=' "$DEPLOYMENT_ROOT/.env" | tail -1 | cut -d= -f2- || true)
  if [[ -n "$RUNTIME_FROM_COMPOSE_ENV" && -f "$RUNTIME_FROM_COMPOSE_ENV/crawler/.env" ]]; then
    SOURCE_ENV=$RUNTIME_FROM_COMPOSE_ENV/crawler/.env
  fi
fi
if [[ -z "$SOURCE_ENV" && -f /open_energy_data_server/runtime/crawler/.env ]]; then
  SOURCE_ENV=/open_energy_data_server/runtime/crawler/.env
fi
if [[ -n "$SOURCE_ENV" ]]; then
  cp "$SOURCE_ENV" "$RUNTIME_ROOT/crawler/.env"
fi
cp "$REPO_ROOT/crawler/data/mapping_eic_to_location.py" "$RUNTIME_ROOT/crawler/data/"
cp "$REPO_ROOT/crawler/data/mapping_p_to_g.json" "$RUNTIME_ROOT/crawler/data/"
cp "$REPO_ROOT/crawler/data/mapping_g_to_p.json" "$RUNTIME_ROOT/crawler/data/"
chmod -R 0777 "$RUNTIME_ROOT"

FMS_BLOCK=""
EXPECTED='["entsoe_api","power_system_data","weather_forecast"]'
if [[ "$INCLUDE_ENTSOE_FMS" == "true" ]]; then
  EXPECTED='["entsoe_api","power_system_data","weather_forecast","entsoe_fms"]'
  FMS_BLOCK='entsoe_fms:
  enable: true
  schema_name: "entsoe_fms"
  schedule: "* * * * *"
  fms_package_window_months: 1
  fms_package_write_mode: "full_upsert"
  run_post_scripts: false
  target_data_items:
    - "EnergyPrices_12.1.D_r3"'
fi

cat > "$RUNTIME_ROOT/CRAWLER_CONFIG.yml" <<YAML
default:
$(write_default_email_config)
  enable: false
  schedule: "* * * * *"
  post_run_scripts: []
  database_uri: "postgresql://opendata:opendata@open-data:5432/opendata?options=--search_path="
entsoe_api:
  enable: true
  schema_name: "entsoe_api"
  schedule: "* * * * *"
  target_datasets:
    - "day_ahead_prices"
  country_code: "DE_LU"
  lookback_days: 1
  lookahead_days: 1
  request_pause_seconds: 0.1
  run_post_scripts: false
power_system_data:
  enable: true
  schema_name: "power_system_data"
  schedule: "* * * * *"
  run_post_scripts: false
weather_forecast:
  enable: true
  schema_name: "weather"
  schedule: "* * * * *"
  forecast_hours: 1
  past_hours: 0
  run_post_scripts: false
  locations:
    - location_id: "berlin"
      name: "Berlin"
      country_code: "DE"
      country_name: "Germany"
      region: "Berlin"
      location_type: "load_center"
      latitude: 52.52
      longitude: 13.405
      aggregation_weight: 1.0
      enabled: true
$FMS_BLOCK
YAML

export OEDS_RUNTIME_DIR=$RUNTIME_DIR
"${COMPOSE[@]}" build scheduler
"${COMPOSE[@]}" up -d open-data
wait_for_container_health oeds-modular-test-open-data "$TIMEOUT_SECONDS" open-data

EXPECTED_CRAWLERS=$EXPECTED "${COMPOSE[@]}" run --rm --no-deps -T -e EXPECTED_CRAWLERS scheduler python - <<'PY'
import json
import os
from pathlib import Path

from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.runtime import CrawlerJobRunner

expected = set(json.loads(os.environ["EXPECTED_CRAWLERS"]))
app = SchedulerApplication(
    config_path=Path("/app/CRAWLER_CONFIG.yml"),
    inventory_path=Path("/app/modular_repos/docs/crawler-inventory.json"),
    workspace_root=Path("/app/modular_repos"),
)
plans = [plan for plan in app.plan_result.plans if plan.crawler_name in expected]
seen = {plan.crawler_name for plan in plans}
missing = sorted(expected - seen)
if missing:
    raise SystemExit(f"missing active crawler plan(s): {', '.join(missing)}")
runner = CrawlerJobRunner(app.factory)
payload = []
for plan in sorted(plans, key=lambda item: item.crawler_name):
    result = runner.run(plan)
    payload.append({
        "job_id": result.job_id,
        "crawler_name": result.crawler_name,
        "crawler_success": result.crawler_success,
        "post_run_success": result.post_run_success,
        "success": result.success,
        "error": result.error,
    })
print(json.dumps(payload, sort_keys=True))
raise SystemExit(0 if all(item["success"] for item in payload) else 1)
PY

cat <<'SQL' | "${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
DO $$
DECLARE
  entsoe_price_rows integer;
  power_rows integer;
  weather_rows integer;
BEGIN
  IF to_regclass('entsoe_api.day_ahead_prices') IS NULL THEN RAISE EXCEPTION 'missing entsoe_api.day_ahead_prices table'; END IF;
  IF to_regclass('power_system_data.powersystemdata') IS NULL THEN RAISE EXCEPTION 'missing power_system_data.powersystemdata table'; END IF;
  IF to_regclass('weather.hourly_forecast') IS NULL THEN RAISE EXCEPTION 'missing weather.hourly_forecast table'; END IF;
  SELECT COUNT(*) INTO entsoe_price_rows FROM entsoe_api.day_ahead_prices;
  SELECT COUNT(*) INTO power_rows FROM power_system_data.powersystemdata;
  SELECT COUNT(*) INTO weather_rows FROM weather.hourly_forecast;
  IF entsoe_price_rows <= 0 THEN RAISE EXCEPTION 'entsoe_api.day_ahead_prices has no rows'; END IF;
  IF power_rows <= 0 THEN RAISE EXCEPTION 'power_system_data.powersystemdata has no rows'; END IF;
  IF weather_rows <= 0 THEN RAISE EXCEPTION 'weather.hourly_forecast has no rows'; END IF;
END
$$;
SELECT
  (SELECT COUNT(*) FROM entsoe_api.day_ahead_prices) AS entsoe_api_day_ahead_price_rows,
  (SELECT COUNT(*) FROM power_system_data.powersystemdata) AS power_system_data_rows,
  (SELECT COUNT(*) FROM weather.hourly_forecast) AS weather_hourly_forecast_rows;
SQL

if [[ "$INCLUDE_ENTSOE_FMS" == "true" ]]; then
  cat <<'SQL' | "${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
DO $$
DECLARE
  fms_price_rows integer;
BEGIN
  IF to_regclass('entsoe_fms."EnergyPrices"') IS NULL THEN RAISE EXCEPTION 'missing entsoe_fms."EnergyPrices" table'; END IF;
  SELECT COUNT(*) INTO fms_price_rows FROM entsoe_fms."EnergyPrices";
  IF fms_price_rows <= 0 THEN RAISE EXCEPTION 'entsoe_fms."EnergyPrices" has no rows'; END IF;
END
$$;
SELECT COUNT(*) AS entsoe_fms_energy_prices_rows FROM entsoe_fms."EnergyPrices";
SQL
fi

echo "active crawler smoke passed"
