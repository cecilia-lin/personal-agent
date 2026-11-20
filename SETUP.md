# Intent setup and sponsor configuration

## 1. Run the local app first

Verified on Windows with Python 3.12.14, Node 24.22.3, and pnpm 11.25.0. Install Python 3.12 and a supported Node LTS plus pnpm on a clean machine.

```powershell
.\scripts\Setup.ps1
.\scripts\Migrate.ps1
.\scripts\Start-Api.ps1 -DemoOnly
# In a second terminal:
.\scripts\Start-Web.ps1
```

Open http://127.0.0.1:5173. API documentation: http://127.0.0.1:8000/api/docs.
The scripts use this machine's bundled runtime when present, otherwise installed Python and pnpm. Dependencies are project-local. Setup preserves an existing .env.

Other platforms can use the same source directly:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r apps/api/requirements.lock.txt
cp -n .env.example .env
pnpm --dir apps/web install --frozen-lockfile
INTEGRATIONS_ENABLED=false python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
# second terminal
pnpm --dir apps/web run dev
```

The on-disk SQLite database survives restarts. Seed is idempotent. Reset is explicit and only clears demo-user records. A fixed DEMO_NOW must include a UTC offset; leave it blank normally.

## 2. Configure only server-side secrets

Copy .env.example to a private .env, fill in authorized project credentials, and restart the API without -DemoOnly. INTEGRATIONS_ENABLED=false explicitly disables outbound sponsor calls. APP_MODE remains demo because identity, financial inputs, and merchant actions are synthetic even when sponsor retrieval/ranking is live.

Do not put keys in VITE_* variables or Git. Never share the local database or raw imported documents in the repository.

## 3. Senso evidence

Set `SENSO_API_KEY` in the server's ignored `.env`. The adapter uses scoped `POST /org/search/context`, documented `POST /org/evals/text` with `kb_accuracy`, and `GET /org/evals/runs/{id}`. Only fictional catalog identities/claims leave the app, not household balances or imported personal documents.

Initialize the approved fictional corpus on a new environment, then retain its ignored `.local/senso-corpus-ledger.json`:

```powershell
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --upload --runs 1
# Later: reuse existing sources and evaluation idempotency keys.
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --runs 3
```

Passages and verdicts do not determine money, stock, or merchant terms. Missing credentials, failed/empty retrieval, source mismatch, and unresolved checks block essential live claims; none silently selects fixtures. Use `-DemoOnly` (`INTEGRATIONS_ENABLED=false`) or explicit `EVIDENCE_PROVIDER=fixture`/`offline` for the labeled offline path.

Required capabilities have a separate verification record and server-owned proposal, approval, and execution gate. Replaceable bulbs, replaceable light modules, and serviceable components are distinct requirements. Live checks establish Arc's bulb and Halo's serviceable components, contradict Fold's module and Mini's bulb claims, and leave Halo's bulb unsupported. The first real check completed within the new ten-minute experiment. Approvals retain native check/claim IDs and approved evidence versions; the current source body is checked before and after evaluation. See [live access and version binding](docs/SENSO_LIVE_ACCESS.md) and [controlled acceptance tests](docs/SENSO_VERIFICATION.md).

References: [Senso quickstart](https://docs.senso.ai/docs/quickstart) and [official evaluation API schema](https://docs.senso.ai/specs/sdk-api.yaml).

## 4. SIE and Statsig

Set SIE_API_KEY. The verified default SIE_BASE_URL is https://api.superlinked.com and the verified ranking model is Qwen/Qwen3-Reranker-0.6B. Model IDs and base URL are configurable.

Set STATSIG_SERVER_SECRET_KEY to a server-side key; legacy STATSIG_SERVER_SECRET is also accepted. In the project, confirm/create enable_reranker with a false default. Only a task whose persisted gate evaluation is true calls SIE ranking. If the model is unavailable, deterministic price ordering records the reason. Ranking never changes eligibility, the target guard, or approval.

The live check confirmed catalog access and a two-item score response. The current gate evaluation is false with no matching rule ID. No experiment result is claimed. SIE extraction, generation/tool selection, and OCR still require implementation; current imports use the documented deterministic text format.

References: [SIE SDK](https://superlinked.com/docs/reference/sdk), [Statsig Server Core](https://docs.statsig.com/server-core/python-core).

## 5. Amplitude

Set AMPLITUDE_API_KEY and AMPLITUDE_SERVER_ZONE (US default). One shared Analytics client is attached to amplitude-ai in metadata_only mode.

Safe product events correlate user/session/task/run IDs. Measured domain tool events use the AI SDK. Emails, utility text, goals, account numbers, balances, and raw prompts are not exported. Model token usage and cost are unknown; no model response or token count is fabricated. SQL commits happen before best-effort telemetry; analytics failure cannot block a cart or bill.

HTTP 200 ingestion was verified. Open the project's event feed and Agent Analytics to verify visibility and session correlation. SDK delivery is not dashboard verification. Existing product-event tracking remains available.

Reference: [Amplitude AI instrumentation](https://amplitude.com/docs/amplitude-ai/agent-analytics/instrument-ai-sdk).

## 6. SingleStore

`SINGLESTORE_API_KEY` provides management access. Inspect existing clusters without changing them:

```powershell
.\scripts\Check-SingleStore.ps1 -Management
```

Configure SINGLESTORE_HOST, PORT, USER, PASSWORD, and DATABASE with a database connection, not a management API token. TLS certificate/hostname checks remain enabled.

```powershell
# Read-only SQL connectivity check, without changing DB_BACKEND:
.\scripts\Check-SingleStore.ps1
# Once SQL access works, explicitly initialize the app tables:
$env:DB_BACKEND='singlestore'
.\scripts\Migrate.ps1 -PrintSchema
.\scripts\Migrate.ps1
```

The generated DDL is in migrations/001_singlestore.sql. Rowstore primary keys include user_id and the shard key is user_id. Owner-scoped parameterized operations and optimistic versions are shared with SQLite; account-row locking serializes financial writes. Payloads use LONGTEXT because real task checkpoints exceed TEXT's 64 KiB limit. Initialization also widens existing TEXT payload columns without deleting records.

Management access, TLS SQL login, schema initialization, and bounded live transaction checks passed against the dedicated personal_agent database. Reproduce the checks with `.\.venv\Scripts\python.exe scripts/verify_singlestore.py`: it uses a unique synthetic owner and removes only its own records. It tests ownership, large Unicode documents, rollback, stale versions, concurrent duplicate cart execution, competing proposals, reservation release, bill deduplication, scan redelivery, and persistence.

The existing local app data remains in SQLite, and DB_BACKEND remains sqlite until explicitly changed. No household records were copied into SingleStore by these checks.

Return to SQLite by setting DB_BACKEND=sqlite. A failed selected SingleStore connection is an error, never a silent SQLite fallback.

## 7. Guild background execution

See [Guild setup](docs/guild/README.md). The bearer-protected review_due_tasks operation is implemented and tested. It checks watches and utility reminders through the same services, persists a run, and never creates carts.

No Guild workspace, hosted agent, schedule, or reachable authenticated backend was configured in this environment. These are explicit remaining setup steps, not a working background deployment.

The official CLI launcher is ready: `.\scripts\Guild.ps1 auth login`. Browser sign-in was deferred at the user's request. A backend bearer token was generated in the ignored local `.env`; install it as the integration credential when a narrow authenticated HTTPS endpoint is ready.

## 8. Cognee connection check

Set COGNEE_API_KEY, then run `.\.venv\Scripts\python.exe scripts/check_cognee.py`. The read-only check verifies the key at Cognee's platform API, discovers the current workspace URL when COGNEE_BASE_URL is blank, and checks its authenticated datasets endpoint. A successful URL is saved in the ignored .env. The configured key and workspace returned HTTP 200.

That connection-check command does not ingest documents or test recall. A separate bounded preparation job now supports sample catalog ingestion, isolated synthetic persona/session memory, actual graph retrieval, and a read-only prepared-memory adapter. It does not alter household data or turn sample prices into executable quotes. See [the data job and actual verification results](docs/COGNEE_DATA_JOB.md). Reference: [Cognee API keys and connection details](https://docs.cognee.ai/cognee-cloud/ui/api-keys).

## 9. Re-run verification

```powershell
.\scripts\Verify.ps1
.\.venv\Scripts\python.exe scripts/smoke.py
# Uses configured keys and bounded synthetic provider checks:
.\.venv\Scripts\python.exe scripts/verify_integrations.py
```

The last command needs network access and may consume a small amount of existing provider credits. Its detailed result is kept in ignored .local/sponsor-verification.json. Do not publish raw environment files or SDK logs.
