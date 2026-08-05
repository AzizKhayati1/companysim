#!/usr/bin/env bash
# Stop the companysim dev servers by killing whatever holds their ports.
#
# Usage:  bash .claude/skills/run-servers/stop.sh [--api-only|--web-only]
#
# Kills by PORT, never by process-name pattern: `pkill -f "node|vite|python"`
# on a dev machine will happily take out the agent session that ran it, or an
# unrelated editor/language server.
set -uo pipefail

API_PORT="${COMPANYSIM_API_PORT:-8611}"   # see wait.sh — pinned by client.ts
WEB_PORT=5173

PORTS=("$API_PORT" "$WEB_PORT")
case "${1:-}" in
  --api-only) PORTS=("$API_PORT") ;;
  --web-only) PORTS=("$WEB_PORT") ;;
  "") ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

for port in "${PORTS[@]}"; do
  pids=$(netstat -ano 2>/dev/null | grep -E "LISTENING" \
         | grep -E "[:.]$port[[:space:]]" | awk '{print $NF}' | sort -u)
  if [ -z "$pids" ]; then
    echo "port $port  already free"
    continue
  fi
  for pid in $pids; do
    if command -v taskkill >/dev/null 2>&1; then
      # Git Bash mangles a leading single slash into a path; // is the escape.
      taskkill //PID "$pid" //F >/dev/null 2>&1
    else
      kill -9 "$pid" 2>/dev/null
    fi
    echo "port $port  killed PID $pid"
  done
done

sleep 1
still=$(netstat -ano 2>/dev/null | grep -E "LISTENING" \
        | grep -E "[:.]($API_PORT|$WEB_PORT)[[:space:]]")
if [ -n "$still" ]; then
  echo "WARNING: still listening:" >&2
  echo "$still" >&2
  exit 1
fi
echo "all requested ports free"
