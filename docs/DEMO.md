# Three-minute Intent demo

Intent helps someone choose an affordable product, check the product feature that matters to them, and approve a demo cart with visible evidence. This recording focuses on the complete Senso purchasing path. Money, products and the merchant are fictional; Senso calls are live. No order or payment is placed.

## Prepare the live environment

Use the existing repository and toolchain. A clean checkout needs Python 3.12+, Node.js and the project's pinned pnpm dependencies. Setup preserves an existing `.env`. Run commands from the repository root.

Windows PowerShell, for a clean checkout:

```powershell
.\scripts\Setup.ps1
.\scripts\Migrate.ps1
```

macOS/Linux, for a clean checkout:

```bash
bash scripts/setup.sh
```

Set these values in the ignored root `.env`, keeping the actual API key private:

```dotenv
APP_MODE=demo
DB_BACKEND=sqlite
INTEGRATIONS_ENABLED=true
EVIDENCE_PROVIDER=senso
SENSO_API_KEY=<your authorized Senso API key>
```

The API requires the local approved-source ledger at `.local/senso-corpus-ledger.json`. Create or reconcile it with the corpus script. Only the four fictional spec sheets are uploaded; the answer key stays local.

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --upload-only
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --runs 1
```

```bash
# macOS/Linux
.venv/bin/python scripts/senso_corpus_check.py --upload-only
.venv/bin/python scripts/senso_corpus_check.py --runs 1
```

Check that all four sources report `ready` and the five corpus checks pass. See [corpus instructions](../fixtures/senso/README.md) for retry behavior and bounded checks. Setup/upload commands do not reset household data. For a clean recording, an explicitly separate `SQLITE_PATH=data/intent-recording.db` starts a separate synthetic database.

Start in fresh terminals so a previous offline-demo environment override is not inherited:

```powershell
# Windows, terminal 1: live Senso, synthetic merchant
.\scripts\Start-Api.ps1
# Windows, terminal 2
.\scripts\Start-Web.ps1
```

```bash
# macOS/Linux, terminal 1
bash scripts/start-api.sh
# macOS/Linux, terminal 2
bash scripts/start-web.sh
```

Open [Intent](http://127.0.0.1:5173/). The live recording uses neither `-DemoOnly` nor `--demo-only`, because those flags explicitly disable provider calls. The [API documentation](http://127.0.0.1:8000/api/docs) is available for inspection. The existing [platform setup guide](LOCAL_MACOS.md) describes the macOS/Linux scripts.

## Recording sequence

Read the actual allowance shown on screen; it depends on saved bills and reservations. The default Arc quote is $82.46 when the seeded HOME15 promotion remains eligible. Preflight the run before recording and show loading/error states honestly if a live call takes longer.

| Time | Screen and action | Suggested narration |
| --- | --- | --- |
| 0:00–0:20 | Home: point to allowance, bills and reservations. | “Intent starts with what I can afford. Its budget and merchant calculations are deterministic.” |
| 0:20–0:45 | Shopping: choose **Repairability**, urgency **Now**, target total **$90**, then **Find options**. | “I choose an explicit requirement. A replaceable bulb, a replaceable module and serviceable components are different facts.” |
| 0:45–1:15 | Compare Arc and Fold. Expand the required-claim evidence. | “Arc's source supports a replaceable bulb. Fold is affordable and marked repairable in the catalog, but its actual spec says the LED module is not user-replaceable. Senso returns a conflict, so its proposal stays blocked.” |
| 1:15–1:50 | Arc: **Review proposal**. Show exact total, supporting passage, check ID and evidence version. Select **Approve & create demo cart**. | “Retrieval and verification have separate states. The server checks the required claim and exact terms again before an approved demo cart can reserve funds.” |
| 1:50–2:15 | Show cart and reduced allowance, then **Remove cart & release reservation**. | “Approval creates a simulated cart, not an order. Removal releases the reservation once.” |
| 2:15–2:45 | Start a new comparison with **Replaceable bulb**. Show Halo's unresolved/unsupported bulb claim. | “Halo has serviceable arm joints and a power supply. That does not prove its bulb is replaceable. Missing evidence blocks the requested feature.” |
| 2:45–3:00 | Show Activity or the stored cart evidence. | “The result is a choice I can inspect: a requirement, a live check, a source passage and exact approved terms. A changed version or unavailable evidence requires another review.” |

If a quote or check changes during the recording, show the blocked state and run a fresh comparison. Keep source details visible rather than bypassing them to finish a cart.

## Evidence recorded so far

The live corpus report `.local/senso-corpus-check.json` at 2026-11-20 23:38 UTC records these results. Each was stable across three application replays, including source/version/passage identity. Each case reused one completed idempotent evaluator run; these are not three independent model evaluations.

| Product requirement | Live result |
| --- | --- |
| Arc: replaceable bulb | Supported |
| Fold: replaceable light module | Conflict |
| Halo: serviceable components | Supported |
| Halo: replaceable bulb | Unsupported |
| Mini: replaceable bulb | Conflict; Mini is also locally ineligible and is not the evidence-only negative case |

The inspected `.local/live-journey-acceptance.json` records an approved Arc cart at $82.46, an otherwise eligible Fold blocked by Senso conflict, a changed product/quote version rejecting a stale proposal, and release of the reservation exactly once. A separate `.local/live-unavailable-acceptance.json` records a controlled missing-key run against the application: required claims became errors, direct proposal creation was rejected, no actions were created, and no fixture fallback occurred. This verifies unavailable-provider behavior under that controlled configuration; it is not an observed Senso service outage. Likewise, the product/quote version change is not evidence that a Senso document was changed live.

Senso returns the real evaluation/check ID, verdict and grounding quote. Some observed evaluator citations omit a native content-version UUID. For those citations, Intent preserves `evaluator_content_version_id: null` and records `version_binding: scoped_context_uuid_and_unchanged_body_before_after_evaluation`: the application's binding to scoped retrieval plus unchanged source body/version number checked before and after evaluation. Do not describe that derived binding as a native evaluator field.

## Other working paths, outside this recording

Utilities still imports and confirms a sample bill into the shared allowance. Flexible intentions can produce Wait and a saved watch; scans remain local/manual unless a real Guild run is observed. The optional prepared-memory panel recalls isolated synthetic Cognee research preferences and compares them with Senso policy evidence; those external sample products remain research-only and cannot create proposals. See [Cognee job details](COGNEE_DATA_JOB.md). These additions do not replace the approval, cart or reservation-release path.
