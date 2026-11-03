#!/usr/bin/env bash
# Stop the app started by ./run.sh (PORT=9000 ./stop.sh if it runs on another port).
# Only stops the Expense Tracker (uvicorn app.main); anything else on the port is left alone.
set -euo pipefail
port="${PORT:-8765}"
pids=()
for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true); do
  # With --reload the port is also held by the reloader's worker, a child of uvicorn.
  ppid="$(ps -o ppid= -p "$pid" | tr -d ' ')"
  if ps -o command= -p "$pid" | grep -q "uvicorn app.main:app" \
     || ps -o command= -p "$ppid" 2>/dev/null | grep -q "uvicorn app.main:app"; then
    pids+=("$pid")
  else
    echo "Port $port is used by another program (pid $pid): $(ps -o command= -p "$pid")" >&2
  fi
done
if [ ${#pids[@]} -eq 0 ]; then
  echo "Expense Tracker is not running on port $port."
  exit 0
fi
kill "${pids[@]}"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  kill -0 "${pids[@]}" 2>/dev/null || { echo "Expense Tracker stopped (port $port)."; exit 0; }
  sleep 0.5
done
echo "Still running after 5s; forcing it to stop." >&2
kill -9 "${pids[@]}" 2>/dev/null || true
echo "Expense Tracker stopped (port $port)."
