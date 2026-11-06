#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Deliberately do not load deployment .env into isolated tests.
export AXIOM_DATA="$(mktemp -d)"
export AXIOM_WORKER=0 AXIOM_TEST_HTTP=0 AXIOM_SECURE_COOKIES=0
export AXIOM_ORIGINS=http://localhost:8015,http://127.0.0.1:8015
export AXIOM_ALLOWED_HOSTS=localhost,127.0.0.1
export AXIOM_PUBLIC_URL=
.venv/bin/python -m pytest -q "$@"
.venv/bin/python -m pip check
