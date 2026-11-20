#!/usr/bin/env bash
# Shared helpers for the macOS/Linux entry points. Source this file.
set -euo pipefail

INTENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$INTENT_ROOT"

intent_require_python() {
  if [[ ! -x "$INTENT_ROOT/.venv/bin/python" ]]; then
    printf '%s\n' 'Run bash scripts/setup.sh first.' >&2
    return 1
  fi
}

intent_pnpm() {
  # Keep the teammate's pnpm lockfile; do not generate a second package lock.
  if command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
  elif command -v npx >/dev/null 2>&1; then
    npx --yes pnpm@11.25.0 "$@"
  else
    printf '%s\n' 'Install Node.js 24 LTS with npm (or pnpm 11.25.0), then retry.' >&2
    return 1
  fi
}
