# Local setup on macOS and Linux

This setup uses the team's existing `apps/web` React/Vite frontend and `apps/api` FastAPI backend. It preserves the shared architecture, API, dependency locks, Windows scripts and provider configuration.

## Start

Prerequisites: Python 3.12+ (3.13 works here), Node.js 22.13+ (24 LTS recommended) and npm or pnpm 11.25.0. The scripts use an installed `pnpm`, or invoke the team's pinned pnpm through `npx` without a global install. Python dependencies use `uv` when available and otherwise pip inside the project virtual environment.

From the repository root:

```bash
bash scripts/setup.sh
```

Setup creates `.venv`, installs the existing locked dependencies, and copies `.env.example` to `.env` only when `.env` is absent. It neither migrates nor resets an existing database. To select a Python executable on a clean setup:

```bash
INTENT_PYTHON=/path/to/python3.13 bash scripts/setup.sh
```

Open two terminals:

```bash
# Terminal 1: synthetic local demo with external integrations disabled
bash scripts/start-api.sh --demo-only
# Add --reload when developing backend code.
```

```bash
# Terminal 2
bash scripts/start-web.sh
```

Open **http://127.0.0.1:5173**. API health: **http://127.0.0.1:8000/api/health**. API documentation: **http://127.0.0.1:8000/api/docs**. Startup creates/seeds a new SQLite database idempotently; existing state survives restarts. Ctrl+C stops each server.

The scripts resolve the repository path themselves and also work when invoked by absolute path from another directory. Use `bash` explicitly; executable-bit changes are unnecessary.

## Verify

```bash
bash scripts/verify.sh
```

This runs the teammate's existing backend invariants and frontend TypeScript/production build. Tests isolate databases and disable external integrations. Build output is `apps/web/dist`. These commands use the existing dependency lockfiles rather than adding npm or Python alternatives.

With the demo API running, optionally exercise the full utility → purchasing → approval → release flow:

```bash
.venv/bin/python scripts/smoke.py
```

The smoke check creates synthetic task, bill and activity records and removes its own demo cart. It does not reset the database or place an order. See the team's [demo scenario](DEMO.md), [setup](../SETUP.md), and [current plan](PLAN.md).

## Provider configuration

`--demo-only` overrides integration and database mode for that API process; it does not rewrite `.env`. To use existing authorized credentials, run `bash scripts/start-api.sh` without the flag. Follow [SETUP.md](../SETUP.md) for provider-specific configuration and verified scope. This setup does not request credentials or run live provider checks.

## Collaborating without duplicate scaffolds

The setup work was based on `origin/codex/intent-foundation`, with shell scripts added alongside the existing Windows entry points. The follow-up foundation review adds focused backend fixes and regression tests; see [review findings](FOUNDATION_REVIEW.md). Continue application work in `apps/`; coordinate shared contract changes through [PLAN.md](PLAN.md). Do not merge a second `frontend/` and `backend/` implementation into this foundation.
