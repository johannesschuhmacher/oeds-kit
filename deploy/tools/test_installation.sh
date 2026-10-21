#!/usr/bin/env bash
set -euo pipefail
DEPLOYMENT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REPO_ROOT=$(cd "$DEPLOYMENT_ROOT/.." && pwd)
cd "$DEPLOYMENT_ROOT"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
COMPOSE=(docker compose --profile crawlers -f compose.yml)
NETWORK=${COMPOSE_PROJECT_NAME:-oeds}_netlocalhost

echo 'Checking Compose, database extensions and readonly access'
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='timescaledb') THEN
    RAISE EXCEPTION 'TimescaleDB missing'; END IF;
  IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='postgis') THEN
    RAISE EXCEPTION 'PostGIS missing'; END IF;
END $$;
SET ROLE readonly;
SELECT count(*) FROM public.metadata;
RESET ROLE;
SQL

echo 'Building the runtime image and testing each layer (fixture data, then real clock scheduling)'
docker build --target runtime -t oeds-test:runtime \
  -f "$DEPLOYMENT_ROOT/docker/Dockerfile.crawler-modular" "$REPO_ROOT"
for stage in core crawlers post runtime; do
  docker run --rm --network "$NETWORK" \
    -e OEDS_DB_HOST=open-data -e OEDS_DB_PORT=5432 \
    -e OEDS_DB_PASSWORD \
    -e OEDS_CRAWLER_CONFIG=/app/CRAWLER_CONFIG.yml \
    -e OEDS_CRAWLER_DATA_DIR=/app/crawler/data \
    -v "$DEPLOYMENT_ROOT/tests:/tests:ro" oeds-test:runtime \
    python /tests/integration.py "$stage"
done

echo 'Checking HTTP services and actual Grafana panel queries'
python3 "$DEPLOYMENT_ROOT/tools/check_dashboards.py"
echo 'Installation integration tests passed'
