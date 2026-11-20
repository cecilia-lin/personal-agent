#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
intent_require_python

intent_api_args=(-m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000)
for option in "$@"; do
  case "$option" in
    --demo-only)
      export APP_MODE=demo DB_BACKEND=sqlite INTEGRATIONS_ENABLED=false
      printf '%s\n' 'Starting the explicit local demo. External integrations are disabled for this process.'
      ;;
    --reload) intent_api_args+=(--reload) ;;
    --help|-h)
      printf '%s\n' 'Usage: bash scripts/start-api.sh [--demo-only] [--reload]' 'Without --demo-only, the backend uses your existing .env provider configuration.'
      exit 0
      ;;
    *) printf 'Unknown option: %s\n' "$option" >&2; exit 2 ;;
  esac
done
exec "$INTENT_ROOT/.venv/bin/python" "${intent_api_args[@]}"
