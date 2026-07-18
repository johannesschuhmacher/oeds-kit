#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-300}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOYMENT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
source "$SCRIPT_DIR/smoke_lib.sh"

cd "$DEPLOYMENT_ROOT"
export COMPOSE_PROJECT_NAME=oeds-modular-test
COMPOSE=(docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml)
CONTAINER=oeds-modular-test-open-data

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
"${COMPOSE[@]}" up -d open-data
wait_for_container_health "$CONTAINER" "$TIMEOUT_SECONDS" open-data

cat <<'SQL' | "${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'readonly') THEN
    RAISE EXCEPTION 'missing readonly role';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
    RAISE EXCEPTION 'missing postgis extension';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'linear_interpolate'
  ) THEN
    RAISE EXCEPTION 'missing public.linear_interpolate';
  END IF;
END
$$;
SELECT 'init assertions passed' AS status;
SQL

echo "isolated DB smoke passed"
