#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or newer is required"'
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
if [[ ! -f .env ]]; then cp .env.example .env; fi
chmod 600 .env
.venv/bin/python -m pip check
printf '%s\n' 'Setup complete. Run: bash scripts/run.sh' 'Ollama is optional for document workflows; configure it for AI answers.'
