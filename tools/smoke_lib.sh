#!/usr/bin/env bash
set -euo pipefail

wait_for_container_health() {
  local container=$1
  local timeout_seconds=$2
  local service_name=${3:-}
  local deadline=$((SECONDS + timeout_seconds))
  local state=""

  while ((SECONDS < deadline)); do
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
    if [[ "$state" == "healthy" ]]; then
      return 0
    fi
    sleep 5
  done

  if [[ -n "$service_name" ]]; then
    "${COMPOSE[@]}" logs --no-color "$service_name" | tail -120 || true
  fi
  echo "$container did not become healthy within ${timeout_seconds}s" >&2
  return 1
}

wait_for_http_ok() {
  local name=$1
  local url=$2
  local timeout_seconds=$3
  local deadline=$((SECONDS + timeout_seconds))
  local code=""

  while ((SECONDS < deadline)); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)
    case "$code" in
      2*|3*) return 0 ;;
    esac
    sleep 5
  done

  echo "$name did not return HTTP 2xx/3xx within ${timeout_seconds}s" >&2
  return 1
}

write_default_email_config() {
  cat <<'YAML'
  email:
    mailhost: ""
    fromaddr: ""
    toaddrs: []
    subject: "OEDS Crawler :crawler_name Critical Error Notification"
    username: ""
    password: ""
YAML
}
