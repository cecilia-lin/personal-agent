# Senso live fact-check access

Live access was proved on November 20, 2026. The new ten-minute experiment began at approximately 23:25 UTC; its first real evaluation finished at 23:28:07 UTC. This supersedes the earlier interrupted experiment that had established retrieval only.

The first probe evaluated “Arc desk light has a replaceable bulb.” with the configured organization and key. It returned `completed`, native verdict `verified`, and check ID `9de8a07f-e758-47e1-bb40-6f096feb3f7a`. It cited the older combined catalog, so it proved API access but did not authorize the final product-specific app path.

## Documented API and mapping

The implementation was checked against the [official REST specification](https://docs.senso.ai/specs/sdk-api.yaml), then exercised live:

- `POST /org/evals/text`: exact product claim, `evaluator=kb_accuracy`, label, `wait=false`, and idempotency key.
- `GET /org/evals/runs/{eval_run_id}`: poll queued/running checks and fetch full detail for completed-summary replays.
- `POST /org/search/context`: product retrieval with approved `content_ids` and `require_scoped_ids=true`.
- `GET /org/kb/nodes/{kb_node_id}/content`: exact body, processing state, and version number. KB documents are not readable through `/org/content/{id}`.

Text evaluation searches the organization-wide KB. Its documented request does not accept `content_ids`. The adapter validates returned citations against the product's approved corpus ledger instead of adding an undocumented scoping field.

| Native result | App state |
| --- | --- |
| `verified` with an approved grounded quote and exact matching claim | `supported` |
| `conflict` | `conflict` |
| `unsupported` | `unsupported` |
| `not_verifiable`, or a gated run | `not_verifiable` |
| Queued/running beyond the bounded wait | `pending` |
| Failed run, source change, or service failure | `error` |

Both the run subject and extracted `source_text` must match the requested claim. Only one unambiguous claim is accepted. Bulb replacement, module replacement, and serviceable components remain separate capabilities.

## Source and version binding

Four fictional spec sheets from `fixtures/senso/` are published; the answer key is never uploaded as evidence. The ignored `.local/senso-corpus-ledger.json` records actual content/node/version IDs, readiness, source body hash, and local source identity.

Observed eval citations often omit optional `content_version_id`. The adapter preserves that omission as `null`, never manufacturing a native version. A supported check requires:

1. Scoped context retrieval returns the approved content ID and actual version UUID.
2. The current KB body hash matches the approved ledger before evaluation.
3. The evaluator returns an approved `entails` citation and an exact quote from that approved body, without grounding failure.
4. The body hash, body version number, and approved ledger identity are unchanged after evaluation.
5. Any evaluator-supplied version ID matches the approved context version.

The response records `scoped_context_uuid_and_unchanged_body_before_after_evaluation`. Evidence retains the context-returned UUID, body hash/version number, quote, content/node IDs, available chunk identity, native relation, check/claim IDs, evaluator version, and timestamp. This explicitly distinguishes returned fields from the app's validated version binding.

When an org-wide run also cites the old combined catalog, extra `entails` citations are recorded as ignored and cannot provide support. An approved citation and exact approved quote are still required. A conflicting outside citation, wrong source version, invented quote, or only unapproved citations cannot authorize a proposal. Unrelated sources are never deleted or rewritten.

## Observed live results

All five cases passed through the shared runtime adapter. The ignored report is `.local/senso-corpus-check.json`.

| Claim | Native verdict / app state | Check ID |
| --- | --- | --- |
| Arc has a replaceable bulb | `verified` / `supported` | `55746f9c-f31c-4ea3-904f-8dc9888c1a1f` |
| Fold has a replaceable module | `conflict` / `conflict` | `5de95ddf-ec86-4fbb-885e-7c9b01de2f98` |
| Halo has serviceable components | `verified` / `supported` | `5479f023-f2a6-4abc-8470-82803e50a174` |
| Halo has a replaceable bulb | `unsupported` / `unsupported` | `3c4471e7-db75-4990-9632-bd6015eecb4d` |
| Mini has a replaceable bulb | `conflict` / `conflict` | `ae064374-1afd-45dc-ad7c-0455edb5f193` |

Each was replayed three times with stable state and approved evidence identity. These are idempotent replays of one evaluator run per claim, not three independent model judgments. The current approved body is checked again on every refresh.

Arc's actual positive quote is “The Arc desk light bulb is user-replaceable without tools.” Fold's sheet says its integrated module is not user-replaceable despite the local catalog assertion. Halo's sheet establishes serviceable arm joints and an external power supply; it does not establish a replaceable bulb. A local repairability flag does not resolve these differences.

## Reproduce

```powershell
# New environment: publish the four sheets with checkpoint/readiness safeguards.
.venv\Scripts\python.exe scripts\senso_corpus_check.py --upload --runs 1
# Existing ledger: reuse sources and evaluation idempotency keys.
.venv\Scripts\python.exe scripts\senso_corpus_check.py --runs 3
```

Set `SENSO_API_KEY` in the server's private `.env` and run the API without `-DemoOnly`. Missing credentials, an absent/unready source ledger, unresolved evidence, and service errors block essential live claims. They never silently select fixtures. Explicit `INTEGRATIONS_ENABLED=false`, `EVIDENCE_PROVIDER=fixture`, or `EVIDENCE_PROVIDER=offline` selects the labeled offline path.

See [application verification coverage](SENSO_VERIFICATION.md) for controlled proposal/approval/execution tests. Real provider calls are distinct from mocked application tests. Product documents and cart actions remain fictional; this is not live checkout or real product certification.
