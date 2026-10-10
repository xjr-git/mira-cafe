#!/usr/bin/env bash
# One-command local start for Linux / macOS
set -e
cd "$(dirname "$0")"
PY=${PY:-python3}
[ -x ".venv/bin/python" ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt
echo "URL: http://127.0.0.1:8000/"
cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
