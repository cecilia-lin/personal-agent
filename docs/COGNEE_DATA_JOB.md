# Intent's isolated knowledge preparation job

`scripts/prepare_cognee_data.py` prepares a small DummyJSON research corpus and explicitly synthetic memory cases independently of the frontend or an HTTP request. It uses the existing Python environment. It does not write active household records, change the selected SQLite backend, create merchant quotes, approve purchases, or reserve a cart.

The intended proof is a confirmed requirement recalled in a new session, compared with fresh, source-scoped Senso evidence. HTTP acceptance, an API-key check, a plausible generated answer, and an illustrative graph do not establish that proof.

## Run from the repository root

Use the existing `.venv`. Credentials belong in the ignored root `.env`; the CLI loads it without printing its contents. Relevant names are `SENSO_API_KEY`, `COGNEE_API_KEY`, and `COGNEE_BASE_URL` (the configured tenant URL). No CLI login or new orchestration framework is required.

Start with six products and an explicit synthetic owner. A dry run can download/cache the public source and prepare local artifacts, but does not publish to Senso or ingest into Cognee:

```powershell
.venv\Scripts\python.exe scripts\prepare_cognee_data.py all --max-products 6 --enrich-products 6 --max-model-calls 12 --concurrency 2 --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --dry-run
```

To execute the same prepared six-product job with live services:

```powershell
.venv\Scripts\python.exe scripts\prepare_cognee_data.py all --max-products 6 --enrich-products 6 --max-model-calls 12 --concurrency 2 --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
```

Resume the specific pending stage when an external operation is still processing:

```powershell
.venv\Scripts\python.exe scripts\prepare_cognee_data.py publish-senso --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
.venv\Scripts\python.exe scripts\prepare_cognee_data.py ingest-cognee --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
.venv\Scripts\python.exe scripts\prepare_cognee_data.py verify --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
.venv\Scripts\python.exe scripts\prepare_cognee_data.py export-graph --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
```

Only after successful live six-product ingestion and graph verification may the same job expand:

```powershell
.venv\Scripts\python.exe scripts\prepare_cognee_data.py all --max-products 24 --enrich-products 6 --max-model-calls 12 --concurrency 2 --synthetic-owner intent-demo-prep --output .local\intent-cognee-smoke --resume
```

Local validation or a dry run does not set the `smoke_verified` condition required for expansion. Keep the same owner and output directory on resume. An existing manifest requires `--resume`. A new output directory creates a new isolated job namespace; it is not a way to replay an ambiguous external upload.

Supported stage names are `fetch`, `normalize`, `enrich`, `validate`, `publish-senso`, `ingest-cognee`, `verify`, `export-graph`, and `all`. Individual publication stages still require validated upstream artifacts. A pending/blocked/failed stage stops `all`. Exit code 0 means the requested run finished without a recorded blocking state; 2 means a stage remains pending/blocked/failed; 1 means a handled exception. Inspect the manifest for the actual stage outcomes.

## Bounds and source interpretation

| Control | Limit |
| --- | --- |
| Selected products | 1–24; begin with six |
| Categories | Two discovered categories when available |
| Specialist product subset | 0–6 |
| Requested specialist model calls | 0–12; current parser fallback makes zero |
| Concurrency ceiling | 1–2; sequential operations also satisfy the ceiling |
| Source download | 5 MB; one all-products attempt, at most ten pagination requests, and a bounded license fetch |
| Senso document | 20,000 characters and 40 KB UTF-8 |
| Senso context results | At most five requested per lookup; returned IDs checked locally |
| Graph export | At most 100 nodes, when supported by the tenant |

DummyJSON is sample/synthetic product data. The snapshot stores its URL, retrieval timestamp, SHA-256, schema version, attribution, license, and exact source bytes. Cached bytes are checked against the saved hash. Selection discovers available categories instead of assuming a category name or catalog size.

Stable IDs are `dummyjson:product:<id>`. The normalized source retains stock, minimum order quantity, source attributes, bounded anonymous review observations, and a single price observation normalized with `Decimal`. Reviewer names and emails are omitted from evidence/memory documents.

Interpretations remain deliberately narrow:

- A 30-day return policy establishes a window, not free return shipping. “No return policy” remains ambiguous.
- Shipping/dispatch wording establishes neither a delivery date nor shipping fees.
- `discountPercentage` is a sample catalog discount, not a coupon or a verified savings baseline.
- Missing currency, measurement units, merchant identity, tax, and fees remain unknown. Minimum order quantity is preserved.
- Review text is an attributed sample opinion, not a specification.
- A downloaded price is one observation, not price history or an executable quote.

The existing desk-light fixtures remain intact. External products have `research_only=true`, no executable quote, and no application product mapping. They cannot be treated as the Arc/Fold/Halo lights. Any eventual cart integration requires separate, explicit demo-merchant currency, quantity, tax, shipping, stock, and discount rules.

## Specialists and model availability

The present fallback is accurately labeled in records and the manifest:

| Role | Current execution |
| --- | --- |
| Product Research | Deterministic parser of source-supported fields |
| Offer and Policy | Actual Senso retrieval plus deterministic policy interpretation |
| Scenario and Memory | Deterministic builder of three explicitly synthetic personas/cases |

Records retain agent/run IDs and source/product references. Later scenario contributions refer to preceding research findings. Synthetic cases include a corrected durable return-window requirement, a purchase intention, a session-only exception, and a Wait/recheck episode. Their demo budgets and recheck events are separate synthetic configuration, never claims about real household finances, real policy changes, purchases, or coupons.

The installed SIE SDK's model catalog was inspected without making a generation call. No generation/extraction model was configured. The missing setting is `SIE_GENERATION_MODEL`, identifying a supported hosted text-generation/extraction model; selecting and wiring a supported model remains pending. Merely adding a setting does not make the current parser path a completed model-agent integration. Existing relevance reranking is a separate capability. Current specialist model usage is zero; any hosted Cognee extraction usage must be reported separately when returned by that service.

## Checkpoints and integrity

The job writes local artifacts beneath the selected output directory, normally ignored `.local/`. `manifest.json` records configuration, namespace, source metadata, stage states, errors, external IDs, ledger entries, timestamps, and model-usage status. Checkpoints use a temporary file followed by replacement.

Key preparation artifacts include:

- `snapshot.json`, `snapshot-manifest.json`, and `source-LICENSE.txt`;
- `normalized.json`, `research-findings.json`, and `personas.json`;
- `documents.json` and `validation.json`;
- `senso-retrievals.json` and `policy-findings.json` after live retrieval;
- provider-specific ingestion, verification, and graph outputs as each stage completes.

Validation compares normalized products with the cached source, rejects duplicate identities/documents and research-to-quote conversion, and seals artifact hashes. Mutation stages reject changed or unvalidated inputs before creating a provider client. Bounds are rechecked when a job resumes with a smaller selection limit.

Senso's ledger is keyed by source ID, document hash, and schema version. It retains the normalized source version and remote content/node/version IDs. The checkpoint is written **before** an upload, then after acceptance or failure. A matching existing ledger entry is not posted again automatically. An upload timeout is `ambiguous`, not permission to repeat the POST. A duplicate response does not cause altered text or deletion of existing content. Reconcile unresolved acceptance/duplicate states using actual returned IDs and the ledger before retrying.

No stage wipes, resets, or overwrites unrelated Senso or Cognee content. Do not delete the ledger to force a retry. Keep credentials, raw provider/account content, and generated job output out of Git.

## What Senso establishes

The publisher uses documented operations on the existing Senso API:

1. `POST /org/kb/raw` publishes the concise sample document.
2. `GET /org/kb/nodes/{kb_node_id}` checks actual `content.processing_status`; HTTP acceptance alone is insufficient.
3. `POST /org/search/context` retrieves passages with `content_ids` and `require_scoped_ids=true`.

The application additionally filters results by the approved content, node, and version IDs. Every retained passage includes actual `content_id`, `content_chunk_id`, `version_id`, `kb_node_id`, passage text, `checked_at`, and local source hash/schema. Unready or unversioned sources cannot be queried as approved evidence.

Policy findings are typed `supported`, `contradicted`, or `unknown`. An ID match alone is insufficient: the source policy statement must occur in the retrieved passage, and domain rules constrain its meaning. For example, an explicit 14-day window contradicts a minimum-30-day requirement, while ambiguous or missing wording remains unknown. Shipping and warranty findings preserve only their actual recorded statements.

This is **context retrieval with deterministic interpretation**, not a separate Senso fact-check API call. The job does not manufacture a check ID or claim that retrieval alone authorizes an application purchase. Existing server-side proposal, approval, execution, quote, budget, and reservation controls remain in force.

## Cognee capability discovery and proof

The adapter uses the configured tenant's authenticated REST API and observed OpenAPI schema. It does not route application data through ChatGPT's connected Cognee memory plugin. An unsupported or changed schema must produce a pending/blocked result instead of guessing a mutation payload.

The observed tenant schema exposes these operations under its API prefix:

- Permanent `POST /remember`: multipart `data`, `datasetName`, `run_in_background=true`, and `self_improvement=false`; no session ID for durable ingestion.
- Session `POST /remember/entry`: dataset/session scope and typed entry JSON. Session entries do not automatically become permanent graph memory.
- `POST /recall`: explicit datasets/dataset IDs, scope, session ID, references, and streaming controls.
- Dataset processing/status endpoints.
- `GET /visualize/json`: explicit dataset ID, a maximum-node bound, and controls that omit unrelated session events.

Public sample catalog knowledge and each private synthetic persona use isolated datasets. A request joining catalog/persona knowledge must explicitly authorize both scopes and join stable product IDs. Shared labels are not proof that graph nodes from different datasets became one canonical entity.

Verification must check five grounded questions, distinguish current-session retrieval from graph recall, and recall the confirmed requirement in a genuinely new session without repeating it in the query. Temporary exceptions must stay in their original session; corrected preferences must supersede earlier ones. Returned references and actual graph nodes/edges are required evidence. Graph exports must preserve raw returned data; disconnected or missing relationships are reported instead of replaced with a decorative graph.

## Application bridge and current live results

The job prepares research knowledge without altering the existing application flows. The Shopping view's explicit "Recall prepared demo memory" action calls the read-only PreferenceMemory adapter in a genuinely new session. It verifies actual graph references, then applies the typed 30-day requirement to fresh scoped Senso passages. The live application check returned one supported and one contradicted research candidate. Both remain Wait with proposals disabled because sample prices are not merchant quotes. No household record, budget or approval was changed. Reproduce against the isolated acceptance API with `python scripts/check_prepared_memory.py`; the local result is `.local/cognee-job-smoke/app-bridge.json`.

The six-product smoke run completed live ingestion and all six verification checks before expansion. The bounded expansion requested at most 24 products; the two discovered categories contained **19** products: five `laptops` and fourteen `mobile-accessories`. No further expansion was performed. The final standalone verification completed at **2026-11-20 23:32 UTC**, with results preserved under `.local/cognee-job-smoke/`.

| Evidence | Current report |
| --- | --- |
| Selected source/category counts | 19 sample products, two categories, zero rejected normalized products |
| Live Senso ready/retrieved counts | 19 ready documents; six-product specialist subset retrieved; 18 typed policy checks |
| Cognee accepted/processed counts | Seven durable files processed across four scoped datasets; three typed session entries |
| Five grounded retrieval checks | All five passed, plus a sixth fresh-session isolation check |
| Actual graph node/edge counts | Catalog bounded export: 84 nodes / 252 edges; persona A: 18 nodes / 28 edges; zero disconnected nodes in either returned subgraph |
| Fresh-session requirement recall | Persona-only graph scope returned the confirmed 30-day requirement and correction of the earlier 14-day preference; the new session returned no old temporary exception |
| App decision changed | The research comparison excludes the 7-day return product under the recalled 30-day requirement; the 90-day product passes that policy check. Both remain Wait pending executable terms. No purchasing task or household preference is modified. |
| Text-generation specialists | Pending; parser fallback, zero generation calls |

Graph similarity search initially retrieved only the first catalog batch, so the expanded all-product return-policy check honestly remained pending. Verification now uses at most three lexical follow-ups of four missing product IDs. Expected policy values are never included in those queries. Question echoes are excluded from fact matching. On this tenant lexical results omit citation metadata, so they count only when their returned content exactly contains an actual exported graph chunk whose `document_id` matches a completed job ledger entry. These derived links are labeled `exact_exported_chunk_text_match`; they are not fabricated provider citation IDs. The final 19-product run passed with this stricter provenance check.

The graph queries use context-only retrieval: they inspect genuine retrieved graph content without another answer-generation call or a new QA write. `verification.json`, `recall/*.json`, `graph-report.json`, and `graphs/*.json` retain the actual checks and provider responses. `graphs/*.html` presents escaped tables from those actual nodes and edges. Counts describe the returned bounded subgraphs, not a claimed total account graph size.

To repeat only verification of this existing job without re-ingesting:

```powershell
.venv\Scripts\python.exe scripts\prepare_cognee_data.py verify --max-products 24 --enrich-products 6 --synthetic-owner intent-demo-cognee --output .local\cognee-job-smoke --resume
```

Run relevant focused/backend checks with the existing environment. Frontend checks are only needed if the UI changes:

```powershell
.venv\Scripts\python.exe -m pytest apps\api\tests\test_senso_preparation.py apps\api\tests\test_cognee_preparation_job.py -q
.venv\Scripts\python.exe -m pytest apps\api\tests -q
```

## Primary references

- [DummyJSON product documentation](https://dummyjson.com/docs/products), [source data](https://github.com/Ovi/DummyJSON/blob/master/database/products.json), and [MIT license](https://github.com/Ovi/DummyJSON/blob/master/LICENSE).
- [Senso quickstart](https://docs.senso.ai/docs/quickstart) and [scoped context retrieval](https://docs.senso.ai/docs/openai-agents-sdk).
- [Cognee API overview](https://docs.cognee.ai/api-reference/introduction), [remember](https://docs.cognee.ai/core-concepts/main-operations/remember), [recall](https://docs.cognee.ai/core-concepts/main-operations/recall), and [graph visualization](https://docs.cognee.ai/guides/graph-visualization). The deployed tenant schema is authoritative for request shapes.
