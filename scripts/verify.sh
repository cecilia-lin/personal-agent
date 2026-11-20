#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
intent_require_python

# Use the same application tests and locked frontend as the Windows workflow.
# Test-only external-call settings are scoped to this command, preserving .env.
APP_MODE=demo DB_BACKEND=sqlite INTEGRATIONS_ENABLED=false \
  PYTHONPATH="$INTENT_ROOT/apps/api" "$INTENT_ROOT/.venv/bin/python" -m pytest apps/api/tests -q
intent_pnpm --dir apps/web run build
