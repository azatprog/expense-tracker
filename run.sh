#!/usr/bin/env bash
# Start the app at http://127.0.0.1:8765 (PORT=9000 ./run.sh for another port).
# The first run creates .venv and installs requirements.txt.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
echo "Expense Tracker → http://127.0.0.1:${PORT:-8765}  (Ctrl+C to stop)"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8765}" "$@"
