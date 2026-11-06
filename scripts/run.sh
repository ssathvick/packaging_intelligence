#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
if [[ ! -f .env ]]; then printf '%s\n' 'Run bash scripts/setup.sh first.' >&2; exit 1; fi
set -a
source .env
set +a
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8015 --workers 1 --no-proxy-headers --no-access-log
