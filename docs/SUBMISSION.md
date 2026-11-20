# Intent submission draft

Project: **Intent — a considered purchase, backed by evidence**

Repository: [cecilia-lin/personal-agent](https://github.com/cecilia-lin/personal-agent)

Demo video: **[ADD VIDEO LINK]**

Team members: **[ADD TEAM NAMES]**

Contact email: **[ADD CONTACT EMAIL]**

## Short description

Intent helps someone choose an affordable product, verify the product feature that matters to them, and approve a demo cart with visible evidence. It combines deterministic budget and merchant checks with live Senso claim verification. Unsupported or contradictory claims block proposals, even when the local catalog says a product is suitable.

## Problem and approach

A recommendation can fit a budget and still depend on an incorrect product claim. Intent makes that dependency visible. The shopper chooses a precise requirement; the app retrieves product information, evaluates the required claim, and shows the supporting passage and check record beside the recommendation. The shopper then reviews exact terms before approving a simulated cart.

The central negative example is deliberate: the fictional Fold catalog describes a replaceable light module, while its uploaded spec says the module is integrated and not user-replaceable. Fold remains locally affordable and repairable, but live Senso evidence blocks its proposal. Halo provides a second distinction: serviceable arm joints and an external power supply do not establish a replaceable bulb.

## What we built

- React/TypeScript/Vite shopping, utilities, watchlist, activity and integration views, backed by Python/FastAPI and Pydantic.
- Live Senso retrieval and `kb_accuracy` checks against four fictional desk-light specifications, with a repeatable upload/readiness script and an approved-source ledger.
- Separate UI states for information retrieved and required claim verified; source passages, real check IDs, product versions and evidence fingerprints remain inspectable.
- Server-side checks before proposal creation, approval and execution. Unsupported, conflicting, pending or unavailable essential claims cannot authorize a cart. Changed terms or evidence require a new review.
- Deterministic complete quotes, promotion validation, budget arithmetic, persisted approvals, cart reservations and idempotent reservation release. Remote evidence calls run outside financial write transactions.
- An isolated Cognee preparation and research-memory path, documented separately, with sample catalog knowledge and synthetic persona memory. Research observations do not become executable merchant quotes.

SQLite remains the selected local authoritative store. Optional sponsor adapters and SingleStore support are documented in the repository; this submission does not claim a household migration, deployed Guild scheduler or production checkout.

## Senso's contribution

Senso supplies the live product passages and claim verdicts that make the core recommendation eligible or blocked. Context retrieval alone is not treated as verification. The evaluation searches the organization's knowledge base, so Intent validates approved product-source citations and their grounding. An unrelated source cannot satisfy the required claim merely because it was retrieved.

The observed live corpus results are Arc bulb **supported**, Fold module **conflict**, Halo serviceable components **supported**, Halo bulb **unsupported**, and Mini bulb **conflict**. All five produced stable application results and evidence across three idempotent replays. The report records one distinct completed evaluator run per case, not three independent model judgments.

The app preserves native evaluator fields as returned. Where a citation omits its content-version UUID, the original field remains null and the app explicitly labels its own binding to scoped retrieval and an unchanged source body/version number checked before and after the evaluation. This distinction is visible in the stored evidence record.

## Demonstrated behavior and limits

The current live application report records a supported, affordable Arc proposal approved into a demo cart at **$82.46**; an otherwise eligible Fold blocked by the Senso conflict; a stale proposal rejected after an actual product/quote version change; and reservation release exactly once. These records are in the ignored local `.local/live-journey-acceptance.json`. A separate controlled missing-key run in `.local/live-unavailable-acceptance.json` produced claim errors, rejected direct proposal creation, created no actions and did not fall back to fixture evidence. That is an observed application failure-path check, not a claimed real Senso service outage.

The four specifications, household values and merchant are fictional demo data. No real order, payment or bank action occurs. The interface supports explicit repairability, replaceable-bulb, replaceable-module and serviceable-components requirements; it does not claim general understanding of arbitrary shopping conditions. The merchant still validates stock, quantities, promotions, tax, shipping and the complete quote independently of Senso.

Source fixture files and the local answer key are intentionally separate. Only the four specification documents are uploaded. Upload checkpoints and exact-content reuse prevent accidental duplicate writes, while ambiguous results remain unresolved until reconciled.

## Running the demonstration

Follow [the three-minute demo guide](DEMO.md) for Windows and macOS/Linux startup, server-side Senso configuration, corpus preparation, the recording sequence and current evidence. Keep credentials in the ignored `.env`. Start the API with live integrations enabled; the explicit offline-demo flags disable Senso calls.

For the recording and submission, fill the video, team and contact fields above. The core story is one complete path: **requirement → live evidence check → affordable exact proposal → explicit approval → demo cart → reservation release**.
