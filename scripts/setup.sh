#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' 'Install Node.js 24 LTS with npm, then retry.' >&2
  exit 1
fi
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 13)) { console.error("Node.js 22.13+ is required; 24 LTS is recommended."); process.exit(1); }'

if [[ ! -x .venv/bin/python ]]; then
  if [[ -z "${INTENT_PYTHON:-}" ]]; then
    for candidate in python3.13 python3.12 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
        INTENT_PYTHON="$candidate"
        break
      fi
    done
  fi
  if [[ -z "${INTENT_PYTHON:-}" ]]; then
    printf '%s\n' 'Install Python 3.12+ or set INTENT_PYTHON to its executable path.' >&2
    exit 1
  fi
  "$INTENT_PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
  "$INTENT_PYTHON" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 12), "Recreate .venv with Python 3.12+"'

if command -v uv >/dev/null 2>&1; then
  UV_CACHE_DIR="${UV_CACHE_DIR:-$INTENT_ROOT/.local/uv-cache}" uv pip install --python .venv/bin/python -r apps/api/requirements.lock.txt
else
  if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip
  fi
  .venv/bin/python -m pip install -r apps/api/requirements.lock.txt
fi
intent_pnpm --dir apps/web install --frozen-lockfile --store-dir "$INTENT_ROOT/.local/pnpm-store"

if [[ ! -e .env ]]; then
  cp .env.example .env
fi
printf '%s\n' 'Ready. In separate terminals:' '  bash scripts/start-api.sh --demo-only' '  bash scripts/start-web.sh' 'Open http://127.0.0.1:5173. See docs/LOCAL_MACOS.md.'
