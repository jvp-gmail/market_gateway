#!/usr/bin/env bash
# Start / stop / restart market_gateway (uvicorn) using MARKET_GATEWAY_PORT from .env (default 8020).
# Run from anywhere:  bash scripts/gateway.sh restart
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_env_val() {
  local key="$1"
  local def="${2:-}"
  local line
  if [[ ! -f .env ]]; then
    echo "$def"
    return
  fi
  line="$(grep -E "^[[:space:]]*${key}=" .env 2>/dev/null | tail -n1 || true)"
  if [[ -z "$line" ]]; then
    echo "$def"
    return
  fi
  local val="${line#*=}"
  val="${val%$'\r'}"
  val="${val#\"}"
  val="${val%\"}"
  val="${val#\'}"
  val="${val%\'}"
  echo "$val"
}

PORT="$(load_env_val MARKET_GATEWAY_PORT 8020)"
if [[ -z "${MARKET_GATEWAY_API_KEY:-}" ]]; then
  export MARKET_GATEWAY_API_KEY="$(load_env_val MARKET_GATEWAY_API_KEY '')"
fi

stop_gateway() {
  if command -v fuser >/dev/null 2>&1; then
    if fuser -k "${PORT}/tcp" 2>/dev/null; then
      echo "Stopped listener on port ${PORT}"
    else
      echo "No listener on port ${PORT}"
    fi
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      # shellcheck disable=SC2086
      kill ${pids} 2>/dev/null || true
      echo "Stopped PID(s) on port ${PORT}: ${pids}"
    else
      echo "No listener on port ${PORT}"
    fi
    return
  fi
  echo "Neither fuser nor lsof found; try: sudo apt install psmisc lsof" >&2
  pkill -f "uvicorn market_gateway.app.main:create_app" 2>/dev/null || true
}

start_gateway() {
  echo "Starting market_gateway on 0.0.0.0:${PORT} (--reload). Ctrl+C to stop."
  exec uv run uvicorn market_gateway.app.main:create_app --factory --host 0.0.0.0 --port "${PORT}" --reload
}

redis_check() {
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli ping
  else
    echo "redis-cli not found; install redis-tools to ping Redis." >&2
  fi
}

http_status() {
  echo "--- GET /health ---"
  curl -sS "http://127.0.0.1:${PORT}/health" || echo "(curl failed)"
  echo
  echo "--- GET /status ---"
  if [[ -z "${MARKET_GATEWAY_API_KEY:-}" ]]; then
    echo "MARKET_GATEWAY_API_KEY not set and not found in .env; cannot call /status." >&2
    return 1
  fi
  curl -sS -H "X-API-Key: ${MARKET_GATEWAY_API_KEY}" "http://127.0.0.1:${PORT}/status" || echo "(curl failed)"
  echo
}

usage() {
  cat <<'EOF'
Usage: bash scripts/gateway.sh <command>

  start     Run uvicorn in the foreground (default port from .env MARKET_GATEWAY_PORT or 8020).
  stop      Kill whatever is listening on that TCP port (fuser or lsof).
  restart   stop then start (foreground).
  status    curl /health and /status (needs MARKET_GATEWAY_API_KEY in env or .env).
  redis     redis-cli ping

Set MARKET_GATEWAY_PORT in .env (see .env.example). Default 8020 avoids colliding with other apps on 8000.
EOF
}

cmd="${1:-}"
case "$cmd" in
  start) start_gateway ;;
  stop) stop_gateway ;;
  restart)
    stop_gateway || true
    sleep 0.5
    start_gateway
    ;;
  status) http_status ;;
  redis) redis_check ;;
  "" | help | -h | --help) usage ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
