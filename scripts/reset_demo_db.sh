#!/usr/bin/env bash
# Kept for existing notes; the reset is scripts/reset_demo_db.py (works on every OS).
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./venv/bin/python scripts/reset_demo_db.py "$@"
