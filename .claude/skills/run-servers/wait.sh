#!/usr/bin/env bash
# Wait for the companysim dev servers to become ready, then smoke-test them.
# Exit 0 only when everything requested is actually serving.
#
# This script does NOT launch anything — see SKILL.md. Launching has to
# happen from the caller (the Bash tool's run_in_background, or a separate
# terminal), because a server backgrounded from inside a script inherits
# that script's descriptors under Git Bash/MSYS and holds it open forever;
# `nohup`, `< /dev/null` and `disown` were all tried and none release it.
#
# Usage:  bash .claude/skills/run-servers/wait.sh [--api-only|--web-only]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

LOG_DIR="${COMPANYSIM_LOG_DIR:-$REPO_ROOT/.claude/skills/run-servers/logs}"
# 8611, NOT uvicorn's default 8000: webapp/src/api/client.ts hardcodes
# API_BASE = "http://localhost:8611" with no env override. Start the API on
# any other port and the UI loads perfectly, then shows "Failed to fetch" on
# every request — which looks like a backend crash but is just a wrong port.
API_PORT="${COMPANYSIM_API_PORT:-8611}"
# 5173 is pinned twice: webapp/vite.config.ts sets strictPort, and
# api/main.py's CORS allow_origins lists only localhost/127.0.0.1:5173.
WEB_PORT=5173

WANT_API=1
WANT_WEB=1
case "${1:-}" in
  --api-only) WANT_WEB=0 ;;
  --web-only) WANT_API=0 ;;
  "") ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

wait_for() {  # wait_for <url> <label> <max_seconds>
  local url="$1" label="$2" max="$3"
  for _ in $(seq 1 "$max"); do
    curl -sf -o /dev/null "$url" && return 0
    sleep 1
  done
  echo "TIMEOUT: $label not ready within ${max}s" >&2
  return 1
}

fail=0
# The API applies pending Alembic migrations on startup (api/database.py's
# init_db, via the lifespan hook), so a cold or stale DB adds a few seconds.
[ "$WANT_API" = 1 ] && { wait_for "http://localhost:$API_PORT/health" API 60 || fail=1; }
[ "$WANT_WEB" = 1 ] && { wait_for "http://localhost:$WEB_PORT/" WEB 60 || fail=1; }

if [ "$fail" != 0 ]; then
  echo "--- api.log (tail) ---";  tail -20 "$LOG_DIR/api.log"  2>/dev/null
  echo "--- vite.log (tail) ---"; tail -20 "$LOG_DIR/vite.log" 2>/dev/null
  exit 1
fi

echo "=== smoke ==="
if [ "$WANT_API" = 1 ]; then
  printf 'GET /health          '; curl -s "http://localhost:$API_PORT/health"; echo
  printf 'GET /orgs            '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    "http://localhost:$API_PORT/orgs"
  printf 'GET /model/status    '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    "http://localhost:$API_PORT/model/status"
fi
if [ "$WANT_WEB" = 1 ]; then
  # Vite serves index.html for any unknown path, so hitting / proves almost
  # nothing. Requesting the real entry module is what exercises the
  # React/TS transform pipeline and fails loudly when it's broken.
  printf 'GET /src/main.tsx    '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    "http://localhost:$WEB_PORT/src/main.tsx"
fi

echo
[ "$WANT_API" = 1 ] && echo "API   http://localhost:$API_PORT      (Swagger UI: /docs)"
[ "$WANT_WEB" = 1 ] && echo "WEB   http://localhost:$WEB_PORT"
echo "logs  $LOG_DIR"
echo "stop  bash .claude/skills/run-servers/stop.sh"
