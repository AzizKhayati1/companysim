#!/usr/bin/env bash
# Start the companysim dev servers. No Claude Code required.
#
# Both ports are hardcoded on the other side of the wire and cannot be
# changed independently: webapp/src/api/client.ts pins the API at 8611 with
# no env override, and api/main.py pins CORS to localhost:5173. Change one
# without the other and the UI renders perfectly, then fails every request.
#
#   ./scripts/start-dev.sh            # both
#   ./scripts/start-dev.sh --api-only
#   ./scripts/start-dev.sh --web-only
#
# Ctrl-C stops whatever this script started.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"

START_API=1
START_WEB=1
case "${1:-}" in
  --api-only) START_WEB=0 ;;
  --web-only) START_API=0 ;;
  "") ;;
  *) echo "usage: $0 [--api-only|--web-only]"; exit 2 ;;
esac

# Nothing in the app auto-loads .env (no python-dotenv dependency), so the
# values have to be exported before uvicorn starts. Absent is fine — the app
# then runs with the LLM features off, which is not an error.
if [ -f .env ]; then
  set -a; . ./.env; set +a
  echo "loaded .env"
else
  echo ".env not found - LLM features will be off (not an error)"
fi

# The venv layout differs by platform; pick whichever exists.
if   [ -x .venv/bin/python ];         then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else
  echo "No venv found. Create one:"
  echo "  python -m venv .venv"
  echo '  pip install -e ".[dev,ml,viz,api,llm]"'
  exit 1
fi

if [ "$START_WEB" = 1 ] && [ ! -d webapp/node_modules ]; then
  echo "webapp/node_modules missing - run: (cd webapp && npm install)"
  exit 1
fi

mkdir -p .dev-logs
PIDS=()
cleanup() {
  echo
  for p in "${PIDS[@]:-}"; do
    [ -n "$p" ] && kill "$p" 2>/dev/null
  done
  exit 0
}
trap cleanup INT TERM

if [ "$START_API" = 1 ]; then
  echo "starting backend  -> http://localhost:8611"
  "$PY" -m uvicorn companysim.api.main:app --port 8611 > .dev-logs/api.log 2>&1 &
  PIDS+=($!)
fi
if [ "$START_WEB" = 1 ]; then
  echo "starting frontend -> http://localhost:5173"
  ( cd webapp && npm run dev > "$ROOT/.dev-logs/vite.log" 2>&1 ) &
  PIDS+=($!)
fi

# The backend runs `alembic upgrade head` from its lifespan hook, so the
# first start after a schema change takes noticeably longer.
echo
echo "waiting for readiness (up to 90s)..."
api_up=$([ "$START_API" = 1 ] && echo 0 || echo 1)
web_up=$([ "$START_WEB" = 1 ] && echo 0 || echo 1)
for _ in $(seq 1 120); do
  [ "$api_up" = 0 ] && curl -sf http://localhost:8611/health >/dev/null 2>&1 && api_up=1
  [ "$web_up" = 0 ] && curl -sf http://localhost:5173/       >/dev/null 2>&1 && web_up=1
  [ "$api_up" = 1 ] && [ "$web_up" = 1 ] && break
  sleep 0.75
done

echo
echo "=== smoke ==="
ok=0
check() {  # label url
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$2" 2>/dev/null)
  if [ "$code" = "200" ]; then
    printf '%-22s HTTP %s\n' "$1" "$code"
  else
    printf '%-22s FAILED (%s)\n' "$1" "${code:-no response}"
    ok=1
  fi
}
if [ "$START_API" = 1 ]; then
  check "GET /health"       http://localhost:8611/health
  check "GET /orgs"         http://localhost:8611/orgs
  check "GET /model/status" http://localhost:8611/model/status
fi
if [ "$START_WEB" = 1 ]; then
  check "GET /src/main.tsx" http://localhost:5173/src/main.tsx
fi

echo
if [ "$ok" = 0 ]; then
  [ "$START_API" = 1 ] && echo "API   http://localhost:8611      (Swagger UI: /docs)"
  [ "$START_WEB" = 1 ] && echo "WEB   http://localhost:5173"
  echo "logs  .dev-logs/"
  echo
  echo "Ctrl-C to stop."
else
  echo "Something did not come up. Log tails:"
  for f in .dev-logs/api.log .dev-logs/vite.log; do
    [ -f "$f" ] && { echo "--- $f ---"; tail -20 "$f"; }
  done
fi

wait
