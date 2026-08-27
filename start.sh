#!/usr/bin/env bash
# One-button starter: launches backend + frontend and, when safely configured,
# the Trade Brain Kite MARKET_DATA_ONLY WebSocket sidecar.
# Ctrl+C cleanly shuts everything down.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_LOG="/tmp/trading-agent-backend.log"
FRONTEND_LOG="/tmp/trading-agent-frontend.log"
KITE_LOG="/tmp/trading-agent-kite-live.log"
BACKEND_HEALTH_URL="http://localhost:${BACKEND_PORT}/api/health"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
HEALTH_TIMEOUT=60

if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[0;33m'; C_BLUE=$'\033[0;34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
  C_RED='' C_GREEN='' C_YELLOW='' C_BLUE='' C_BOLD='' C_RESET=''
fi

log()  { echo "${C_BLUE}[start]${C_RESET} $*"; }
ok()   { echo "${C_GREEN}[ok]${C_RESET}    $*"; }
warn() { echo "${C_YELLOW}[warn]${C_RESET}  $*"; }
err()  { echo "${C_RED}[err]${C_RESET}   $*" 1>&2; }

cd "$ROOT_DIR"
if [[ ! -d "venv" ]]; then
  err "No venv found at ./venv. Create one first:"
  err "  python3 -m venv venv && source venv/bin/activate && pip install -e ."
  exit 1
fi
if [[ ! -d "frontend/node_modules" ]]; then
  warn "frontend/node_modules missing. Running 'npm install' (one-time setup)..."
  (cd frontend && npm install)
fi

free_port() {
  local port="$1"; local pids
  pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    warn "Port ${port} is in use. Killing existing process(es): ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 2
    pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
      sleep 1
    fi
  fi
}

free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

BACKEND_PID=""; FRONTEND_PID=""; KITE_PID=""; TAIL_PID=""
cleanup() {
  echo
  log "Shutting down..."
  for pid in "$TAIL_PID" "$KITE_PID" "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  free_port "$BACKEND_PORT" >/dev/null 2>&1 || true
  free_port "$FRONTEND_PORT" >/dev/null 2>&1 || true
  ok "Stopped."
}
trap cleanup EXIT INT TERM

log "Starting backend on :${BACKEND_PORT}..."
: > "$BACKEND_LOG"
(
  cd "$ROOT_DIR"
  # shellcheck disable=SC1091
  source venv/bin/activate
  exec uvicorn backend.app:app --reload --port "$BACKEND_PORT"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Check .env without sourcing secrets into this shell/frontend environment.
KITE_LIVE_READY="$("$ROOT_DIR/venv/bin/python" - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values('.env')
keys = ('KITE_API_KEY', 'KITE_ACCESS_TOKEN', 'KITE_LIVE_SUBSCRIPTIONS')
print('1' if all(str(cfg.get(k) or '').strip() for k in keys) else '0')
PY
)"
if [[ "$KITE_LIVE_READY" == "1" ]]; then
  log "Starting Kite MARKET_DATA_ONLY live stream..."
  : > "$KITE_LOG"
  (
    cd "$ROOT_DIR"
    # shellcheck disable=SC1091
    source venv/bin/activate
    exec python scripts/tradebrain_kite_live_stream.py
  ) >>"$KITE_LOG" 2>&1 &
  KITE_PID=$!
else
  log "Kite live stream not configured; Yahoo/Kite-REST fallback policy remains available."
fi

log "Starting frontend on :${FRONTEND_PORT}..."
: > "$FRONTEND_LOG"
(
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --port "$FRONTEND_PORT"
) >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

wait_until_healthy() {
  local url="$1"; local label="$2"; local pid="$3"; local elapsed=0
  while (( elapsed < HEALTH_TIMEOUT )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      err "${label} process died unexpectedly."
      return 1
    fi
    if curl -sf -o /dev/null --max-time 2 "$url" 2>/dev/null; then return 0; fi
    sleep 1; elapsed=$((elapsed + 1))
    if (( elapsed % 5 == 0 )); then log "${label} starting... (${elapsed}s)"; fi
  done
  err "${label} didn't become healthy within ${HEALTH_TIMEOUT}s."
  return 1
}

wait_until_healthy "$BACKEND_HEALTH_URL" "Backend" "$BACKEND_PID" || exit 1
ok "Backend ready at http://localhost:${BACKEND_PORT}"
wait_until_healthy "$FRONTEND_URL" "Frontend" "$FRONTEND_PID" || exit 1
ok "Frontend ready at ${FRONTEND_URL}"

if [[ -n "$KITE_PID" ]]; then
  sleep 1
  if kill -0 "$KITE_PID" 2>/dev/null; then
    ok "Kite MARKET_DATA_ONLY stream process running."
  else
    warn "Kite stream did not stay up; app will continue with REST/Yahoo fallback. See $KITE_LOG"
    KITE_PID=""
  fi
fi

log "Opening ${FRONTEND_URL} in browser..."
if command -v open >/dev/null 2>&1; then
  open "$FRONTEND_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$FRONTEND_URL" >/dev/null 2>&1 &
elif command -v start >/dev/null 2>&1; then
  start "$FRONTEND_URL" >/dev/null 2>&1 &
else
  warn "Couldn't auto-open browser. Visit ${FRONTEND_URL} manually."
fi

echo
ok "${C_BOLD}Servers are running.${C_RESET}"
echo "  Backend logs:  $BACKEND_LOG"
echo "  Frontend logs: $FRONTEND_LOG"
if [[ -n "$KITE_PID" ]]; then echo "  Kite live log: $KITE_LOG"; fi
echo "  Frontend URL:  ${FRONTEND_URL}"
echo
log "Tailing logs. Press Ctrl+C to stop everything."
echo

if [[ -n "$KITE_PID" ]]; then
  tail -F "$BACKEND_LOG" "$FRONTEND_LOG" "$KITE_LOG" 2>/dev/null &
else
  tail -F "$BACKEND_LOG" "$FRONTEND_LOG" 2>/dev/null &
fi
TAIL_PID=$!

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  err "Backend exited unexpectedly. Last 20 lines:"
  tail -n 20 "$BACKEND_LOG" 1>&2
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  err "Frontend exited unexpectedly. Last 20 lines:"
  tail -n 20 "$FRONTEND_LOG" 1>&2
fi
exit 1
