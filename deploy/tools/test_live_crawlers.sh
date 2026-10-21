#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -lt 1 || ! -f $1 ]]; then
  echo 'Usage: bash tools/test_live_crawlers.sh /path/to/crawler.env [--source kit|core|all] [--reset]' >&2
  exit 2
fi
ENV_FILE=$(realpath "$1")
shift
DEPLOYMENT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK="$HOME/oeds-crawler-validation"
if [[ $ENV_FILE == "$WORK/.env" ]]; then
  echo 'Use the original environment file, not the temporary validation copy.' >&2
  exit 2
fi

install -d -m 700 "$WORK"
install -d -m 755 "$WORK/initdb"
install -m 644 "$DEPLOYMENT_ROOT"/docker/initdb/{09-bootstrap-roles.sh,10-init.sql} "$WORK/initdb/"
install -m 600 "$DEPLOYMENT_ROOT/tests/live_crawlers.py" "$WORK/live_crawlers.py"
install -m 600 "$ENV_FILE" "$WORK/.env"
trap 'rm -f -- "$WORK/.env"' EXIT

if ! docker network inspect oeds-crawler-validation >/dev/null 2>&1; then
  docker network create oeds-crawler-validation >/dev/null
fi
if ! docker container inspect oeds-crawler-validation-db >/dev/null 2>&1; then
  docker run -d --name oeds-crawler-validation-db --network oeds-crawler-validation \
    --memory 2g -e POSTGRES_USER=opendata -e POSTGRES_PASSWORD=opendata \
    -e POSTGRES_DB=opendata -v "$WORK/initdb:/docker-entrypoint-initdb.d:ro,z" \
    timescale/timescaledb-ha:pg18.3-ts2.26.3-oss \
    -c max_worker_processes=96 -c timescaledb.max_background_workers=64 \
    -c timescaledb.telemetry_level=off >/dev/null
fi
for attempt in {1..60}; do
  if docker exec -e PGPASSWORD=opendata oeds-crawler-validation-db \
    psql -h 127.0.0.1 -U opendata -d opendata -v ON_ERROR_STOP=1 \
    -c 'SELECT 1 FROM public.metadata LIMIT 0' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker exec oeds-crawler-validation-db psql -U opendata -d opendata \
  -v ON_ERROR_STOP=1 -c 'SELECT 1 FROM public.metadata LIMIT 0' >/dev/null

echo "Testing live sources. Private results: $WORK/logs"
python3 "$WORK/live_crawlers.py" --user "$(id -u):$(id -g)" "$@"
