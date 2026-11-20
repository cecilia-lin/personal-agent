#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
if [[ ! -d apps/web/node_modules ]]; then
  printf '%s\n' 'Run bash scripts/setup.sh first.' >&2
  exit 1
fi
intent_pnpm --dir apps/web run dev
