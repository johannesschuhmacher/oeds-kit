#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-900}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOYMENT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
source "$SCRIPT_DIR/smoke_lib.sh"

cd "$DEPLOYMENT_ROOT"
export COMPOSE_PROJECT_NAME=oeds-modular-test
COMPOSE=(docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml)
PROFILED_COMPOSE=(docker compose --profile crawlers -f compose.yml -f compose.modular.yml -f compose.test.yml)
RUNTIME_DIR=.tmp/runtime-stack
RUNTIME_ROOT=$DEPLOYMENT_ROOT/$RUNTIME_DIR

cleanup() {
  "${PROFILED_COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT

cleanup
mkdir -p "$RUNTIME_ROOT/crawler/data" "$RUNTIME_ROOT/logs" "$RUNTIME_ROOT/crawler_admin_state"
chmod -R 0777 "$RUNTIME_ROOT"
cat > "$RUNTIME_ROOT/CRAWLER_CONFIG.yml" <<YAML
default:
$(write_default_email_config)
  enable: false
  schedule: "0 4 * * *"
  post_run_scripts: []
  database_uri: "postgresql://opendata:opendata@open-data:5432/opendata?options=--search_path="
smard:
  enable: false
  schema_name: "smard"
  schedule: "0 4 * * *"
  post_run_scripts:
    - "scripts/gapfill_smard.py"
YAML

export OEDS_RUNTIME_DIR=$RUNTIME_DIR
"${PROFILED_COMPOSE[@]}" build crawler-admin
"${PROFILED_COMPOSE[@]}" up -d open-data open-postgrest grafana crawler-admin
wait_for_container_health oeds-modular-test-open-data "$TIMEOUT_SECONDS" open-data
wait_for_http_ok PostgREST http://127.0.0.1:13001/ "$TIMEOUT_SECONDS"
wait_for_http_ok Grafana http://127.0.0.1:13006/api/health "$TIMEOUT_SECONDS"
wait_for_http_ok "Crawler admin" http://127.0.0.1:13010/ "$TIMEOUT_SECONDS"

echo "modular stack smoke passed"
