# Intent — shared product and delivery plan

Updated November 20, 2026. This is the team's current scope and implementation status. Start here, then read [SETUP](../SETUP.md) and [verification](VERIFICATION.md).

## Product

Intent is a personal purchasing agent: it connects what someone wants, when they need it, their target total price, and their household commitments. It gives an explicit Buy, Wait, or Skip decision with evidence and a durable watchlist.

The architecture stays React/Vite/TypeScript → FastAPI/Pydantic → one owner-scoped SQL repository. SQLite is the functioning local store; SingleStore uses the same repository contract. Interactive and background work share the Python domain services. There is no second agent framework.

## Decision contract

| Decision | Current rule | Available action |
|---|---|---|
| Buy | At least one complete eligible quote meets the target when set; urgency is now/soon, or a flexible purchase has reached its target | Review exact terms, approve, create one demo cart; optionally save a watch |
| Wait | Eligible quote exceeds the target, or urgency is flexible with no target | Save a watch and check later observed quotes |
| Skip | No complete quote meets budget, hard limit, stock, preference, and configured evidence requirements | Review reasons and start a revised intention |

Target price means the complete total after discount, tax, and shipping. The hard limit and household allowance are always enforced. “Now” does not override the target. Price history is explicitly seeded sample item-price data with timestamps, before taxes/shipping/discounts. It does not determine eligibility or predict future prices.

## Working now

- Promotion email text import, source retention, typed restrictions, rejected-offer reasons, and independently validated demo promotion codes.
- Confirmed utility text import, identity deduplication, bill revisions/history, comparable-period amount changes, one unpaid commitment, and a durable review card.
- One reproducible spending allowance shared by both flows.
- Exact-quote approval, fresh revalidation, atomic/idempotent cart and reservation creation, and one-time reservation release.
- Urgency, target, Buy/Wait/Skip, timestamped sample history, durable watches, archive, and watch rechecks.
- Bounded manual scan plus authenticated Guild tool; stable platform run IDs deduplicate trigger redelivery.
- Senso evidence retrieval with retained source/version identifiers; failure does not become fixture success.
- SIE relevance adapter behind a persisted Statsig gate; hard financial checks remain deterministic.
- Amplitude product metadata and measured tool events via the Analytics + AI SDKs, emitted after SQL commit.
- Source views, task checkpoints, audit trail, tests, setup scripts, and provider diagnostics.

## Delivery gates

| Gate | Status | Evidence / next requirement |
|---|---|---|
| Both local flows | Complete | API smoke and browser walkthrough; test suite |
| Intent decision and watch behavior | Complete locally | Buy/Wait/Skip, target guard, restart, scan, and archive checks |
| Senso | Verified retrieval | Matching passage with content and version IDs |
| SIE | Verified catalog + scoring | Extraction, generation, and OCR remain unimplemented |
| Statsig | Verified initialization + evaluation | Default false; confirm/create enable_reranker gate and configure intended rule |
| Amplitude | HTTP delivery verified | Agent SDK instrumentation checked locally; dashboard/session visibility still needs review |
| Guild hosted execution | Pending | Workspace access, narrowly exposed authenticated backend, integration installation, trigger and schedule |
| SingleStore | Verified bounded live checks | TLS SQL, schema, isolation, rollback, concurrent duplicate execution and persistence passed; SQLite still holds current local app records |
| Cognee | Connection verified | Key and workspace access succeed; remember/recall adapter remains unimplemented |
| Public deployment / real purchasing | Out of scope | This build is a fixed-user local demo |

Configuration is not proof of a successful provider call. Runtime status and the verification report distinguish the scope of each check.

## Team workstreams

Owners are deliberately unassigned until teammates claim them.

| Track | Files to own | Next concrete deliverable |
|---|---|---|
| Models and canonical state | integrations/sie.py, repositories/, extraction adapter work | Confirm hosted extraction/generation capabilities; implement model-assisted extraction with typed validation; validate SingleStore transactions |
| Purchasing experience | apps/web/, services/intent.py, services/merchant.py | Refine explanation of targets and evidence; validate additional sample categories without changing shared money rules |
| Utilities and background | services/documents.py, scan handler, docs/guild/ | Install the Guild integration and verify one UI-closed watch/reminder run; verify analytics sessions in dashboard |

Coordinate changes to domain/models.py, services/agent.py, and API contracts before editing them. Use a small branch and PR per deliverable. Keep the existing application and shared handler; do not generate separate scaffolds.

## Acceptance for the next shared demo

1. Fresh seed: allowance is $200.
2. Confirm the $148 sample electricity bill: allowance becomes $164 with one revised obligation.
3. Target $70, flexible urgency: Wait for the $82.46 Arc quote; save and recheck the watch.
4. New intention, target $90, urgency now: Buy. Approve the exact $82.46 quote, create the demo cart, reserve $82.46.
5. Remove the cart: allowance returns to $164 exactly once.
6. Inspect timestamped sample history, source evidence, and audit events.
7. Show a deduplicated reminder/watch card. Call it a local scan until a Guild run is observed and recorded.

## Deferred scope

Merchant negotiation, live historical-price feeds, future-price predictions, live checkout, bank connections, payment, investment recommendations, Gmail OAuth, arbitrary website automation, and notifications to other people. PDF/image OCR is unsupported until there is an implemented and verified path.
