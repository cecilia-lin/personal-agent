# Intent — personal purchasing agent

**Team alignment:** [current plan and scope](docs/PLAN.md) · [verified status](docs/VERIFICATION.md) · [setup](SETUP.md) · [remaining work](NEXT_STEPS.md).

A local purchasing agent with explicit Buy/Wait/Skip decisions, urgency, target prices, clearly labeled sample price history, and a persisted watchlist. Two complete paths share the same spending context:

- Import and confirm a utility bill → update one commitment → recalculate the allowance → save a review card.
- Import promotional email → compare complete product quotes → review exact terms → approve a merchant-validated demo cart → reserve funds → remove the cart and release its reservation.

React + Vite + TypeScript, FastAPI + Pydantic, and durable SQLite. A SingleStore repository/DDL path and sponsor adapters are included; see [SETUP.md](SETUP.md) for the exact verified scope. No live checkout, payment, bank connection, or production authentication.

## Start on this Windows machine

From the repository root, dependencies are already installed. Open two PowerShell terminals:

```powershell
# Terminal 1: deterministic local demo, external integrations explicitly disabled
.\scripts\Start-Api.ps1 -DemoOnly

# Terminal 2
.\scripts\Start-Web.ps1
```

Open [Intent](http://127.0.0.1:5173/). The API is at [API docs](http://127.0.0.1:8000/api/docs). Stop each server with Ctrl+C. Use `-Reload` on Start-Api during backend development.

Start-Api without `-DemoOnly` uses your private .env and configured providers. A failed configured live provider is shown as an error; it does not masquerade as a fixture result.

For a clean checkout:

```powershell
.\scripts\Setup.ps1
.\scripts\Migrate.ps1
.\scripts\Start-Api.ps1 -DemoOnly
# In another terminal:
.\scripts\Start-Web.ps1
```

Setup uses installed Python/pnpm or the bundled Codex runtimes on this machine. Prerequisites elsewhere: Python 3.12+, a supported Node LTS (verified here with Node 24.22.3), and pnpm 11.25.0. It creates only project-local dependencies and preserves an existing .env.

## Seed, verify, and build

Startup seeds a new demo database idempotently. Data lives in `data/personal-agent.db`, independently of the server process.

```powershell
# With the API running: preserve existing records
.\scripts\Seed.ps1
# Explicitly clear only demo-owned records and regenerate relative-date fixtures
.\scripts\Seed.ps1 -Reset

# Isolated temporary SQLite databases; external services disabled by the tests
.\scripts\Verify.ps1
# Exercise the real running API; leaves a bill/task/audit, removes its own demo cart
.\.venv\Scripts\python.exe scripts/smoke.py
```

Verify runs backend invariants plus frontend TypeScript and production build. Output is `apps/web/dist`. Python versions are pinned in `apps/api/requirements.lock.txt`; frontend dependencies are pinned in `apps/web/pnpm-lock.yaml`.

## Try the two flows

1. Open Utilities → Use sample bill → Extract bill → review fields → Confirm bill & update allowance. Initial allowance $200 becomes $164; the $148 electricity bill replaces the existing $112 obligation. Autopay scheduled remains unpaid.
2. Open Shopping → Find options. The Arc desk light has an $89 baseline item price; HOME15 discounts $13.35, shipping is $0, tax is $6.81, and the complete cart total is $82.46.
3. Review proposal → Approve & create demo cart. The merchant independently validates the code. The allowance becomes $81.54. No order or payment occurs.
4. Remove cart & release reservation. Allowance returns to $164 once. View Activity for persisted evidence and checks.
5. Shopping → set urgency Flexible and a target of $70 → Find options → Wait → Save to watchlist. View dated sample history; no future price is predicted.
6. Watchlist → Check watches & reminders, or Home → Run scan now. Review cards are deduplicated. This is a local manual run, not Guild.

The sample category is replaceable. Text extraction is deliberately limited to documented field labels, not a general natural-language or OCR model. Use the sample buttons to see the input format; unsupported PDF/image bills are rejected clearly.

## Navigation and source map

- `apps/web/src/`: Home, Shopping, Watchlist, Utilities, Activity, Integrations, and source/confirmation dialogs.
- `apps/api/app/services/`: shared task handler, deterministic money, imports, promotions, cart validation.
- `apps/api/app/repositories/`: owner-scoped SQL operations and dialect-specific schema.
- `apps/api/app/integrations/`: provider contracts, Amplitude AI, Statsig, SIE ranking, and Senso adapters, explicit states.
- `fixtures/demo.json`: household and base catalog; additional relative-date promotion/bill fixtures are in `Documents.seed`.
- [Architecture](docs/ARCHITECTURE.md), [API contracts](docs/API.md), [team workstreams](docs/TEAM_TASKS.md), [demo script](docs/DEMO.md), [remaining work](NEXT_STEPS.md).

This is a fixed synthetic local user (`demo-user`), not production authentication. The app binds to loopback. Do not expose the whole demo API publicly; the narrow background tool has separate bearer authentication.
