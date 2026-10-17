#!/usr/bin/env bash
# Start backend (FastAPI :8001) and frontend (Vite :5173) together.
# Press Ctrl+C once to stop both.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]; then
  echo "Setting up Python environment..."
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Installing frontend packages..."
  (cd "$ROOT/frontend" && npm install --silent)
fi

for port in 8001 5173; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use (is the app already running in another tab?)."
    echo "Stop it there with Ctrl+C, or run:  lsof -ti :$port | xargs kill"
    exit 1
  fi
done

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping servers..."
  kill 0 2>/dev/null  # signal every process started by this script
}
trap cleanup INT TERM EXIT

(cd "$ROOT/backend" && exec .venv/bin/uvicorn app.main:app --reload --port 8001) &
(cd "$ROOT/frontend" && exec npm run dev -- --port 5173 --strictPort) &

echo
echo "  App:      http://localhost:5173"
echo "  API docs: http://localhost:8001/docs"
echo "  Press Ctrl+C to stop both."
echo

wait
