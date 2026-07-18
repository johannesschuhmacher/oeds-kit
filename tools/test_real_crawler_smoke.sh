#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS=900
START_DATE="2024-06-02 22:00:00"
RUN_POST_SCRIPTS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout-seconds) TIMEOUT_SECONDS=$2; shift 2 ;;
    --start-date) START_DATE=$2; shift 2 ;;
    --run-post-scripts) RUN_POST_SCRIPTS=true; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOYMENT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
source "$SCRIPT_DIR/smoke_lib.sh"

cd "$DEPLOYMENT_ROOT"
COMPOSE=(docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml)
RUNTIME_DIR=.tmp/runtime-real-crawler
RUNTIME_ROOT=$DEPLOYMENT_ROOT/$RUNTIME_DIR

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT

cleanup
mkdir -p "$RUNTIME_ROOT/crawler/data" "$RUNTIME_ROOT/logs"
chmod -R 0777 "$RUNTIME_ROOT"
if [[ "$RUN_POST_SCRIPTS" == "true" ]]; then
  POST_RUN_BLOCK='  post_run_scripts:
    - "scripts/gapfill_smard.py"'
else
  POST_RUN_BLOCK='  post_run_scripts: []'
fi
cat > "$RUNTIME_ROOT/CRAWLER_CONFIG.yml" <<YAML
default:
$(write_default_email_config)
  enable: false
  schedule: "* * * * *"
  post_run_scripts: []
  database_uri: "postgresql://opendata:opendata@open-data:5432/opendata?options=--search_path="
smard:
  enable: true
  schema_name: "smard"
  schedule: "* * * * *"
  default_start_date: "$START_DATE"
  run_post_scripts: $RUN_POST_SCRIPTS
$POST_RUN_BLOCK
YAML

export OEDS_RUNTIME_DIR=$RUNTIME_DIR
"${COMPOSE[@]}" build scheduler
"${COMPOSE[@]}" up -d open-data
wait_for_container_health oeds-modular-test-open-data "$TIMEOUT_SECONDS" open-data

"${COMPOSE[@]}" run --rm --no-deps -T scheduler python - <<'PY'
import json
from pathlib import Path

from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.runtime import CrawlerJobRunner

app = SchedulerApplication(
    config_path=Path("/app/CRAWLER_CONFIG.yml"),
    inventory_path=Path("/app/modular_repos/docs/crawler-inventory.json"),
    workspace_root=Path("/app/modular_repos"),
)
plans = [plan for plan in app.plan_result.plans if plan.crawler_name == "smard"]
if len(plans) != 1:
    raise SystemExit(f"expected exactly one smard plan, got {len(plans)}")
result = CrawlerJobRunner(app.factory).run(plans[0])
print(json.dumps({
    "job_id": result.job_id,
    "crawler_success": result.crawler_success,
    "post_run_success": result.post_run_success,
    "success": result.success,
    "error": result.error,
    "post_run_results": [
        {
            "command": item.command,
            "returncode": item.returncode,
            "success": item.success,
            "error": item.error,
        }
        for item in result.post_run_results
    ],
}, sort_keys=True))
raise SystemExit(0 if result.success else 1)
PY

cat <<'SQL' | "${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
DO $$
DECLARE
  smard_rows integer;
  price_rows integer;
  metadata_rows integer;
BEGIN
  IF to_regclass('smard.smard') IS NULL THEN RAISE EXCEPTION 'missing smard.smard table'; END IF;
  IF to_regclass('smard.prices') IS NULL THEN RAISE EXCEPTION 'missing smard.prices table'; END IF;
  SELECT COUNT(*) INTO smard_rows FROM smard.smard;
  SELECT COUNT(*) INTO price_rows FROM smard.prices;
  SELECT COUNT(*) INTO metadata_rows FROM public.metadata WHERE schema_name = 'smard';
  IF smard_rows <= 0 THEN RAISE EXCEPTION 'smard.smard has no rows'; END IF;
  IF price_rows <= 0 THEN RAISE EXCEPTION 'smard.prices has no rows'; END IF;
  IF metadata_rows <> 1 THEN RAISE EXCEPTION 'expected one smard metadata row, got %', metadata_rows; END IF;
END
$$;
SELECT
  (SELECT COUNT(*) FROM smard.smard) AS smard_rows,
  (SELECT COUNT(*) FROM smard.prices) AS price_rows,
  (SELECT COUNT(*) FROM public.metadata WHERE schema_name = 'smard') AS metadata_rows;
SQL

if [[ "$RUN_POST_SCRIPTS" == "true" ]]; then
  cat <<'SQL' | "${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
DO $$
DECLARE
  gapfilled_rows integer;
BEGIN
  IF to_regclass('smard.smard_gapfilled') IS NULL THEN RAISE EXCEPTION 'missing smard.smard_gapfilled table'; END IF;
  SELECT COUNT(*) INTO gapfilled_rows FROM smard.smard_gapfilled;
  IF gapfilled_rows <= 0 THEN RAISE EXCEPTION 'smard.smard_gapfilled has no rows'; END IF;
END
$$;
SELECT COUNT(*) AS smard_gapfilled_rows FROM smard.smard_gapfilled;
SQL
fi

echo "real crawler smoke passed"
