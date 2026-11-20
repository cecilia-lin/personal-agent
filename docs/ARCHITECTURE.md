# Implemented architecture

The React client reads persisted backend data over /api through Vite's local proxy. FastAPI owns one application service. Interactive task runs and manual/authenticated background scans call the same service; there is no queue, second agent framework, or competing scheduler.

## State and invariants

Each SQL table has (user_id, id) as its primary key, a monotonically increasing version, and a JSON payload. Tables are whitelisted in the repository. Values use parameterized queries and every read/write includes the owner. SQLite uses BEGIN IMMEDIATE for mutations. SingleStore uses a rowstore schema with SHARD KEY(user_id), an owned account-row lock, and conditional version updates. Its payloads use LONGTEXT, with a widening migration for the initial TEXT schema. TLS SQL access and bounded live ownership, rollback, concurrency, deduplication and persistence checks passed; the existing local app records still use SQLite.

Current tables: accounts, bills, preferences, sessions, tasks, products, proposals, actions, audit_events, analytics_events, holdings (legacy read-only fixture), sources, source_versions, offers, merchant_offers, bill_imports, bill_history, reservations, next_actions, runs, adjustments, watch_items, price_history.

Money is integer USD cents. Cash snapshot, subsequent adjustments, unpaid commitments, safety buffer, active reservations, and the shopping cap remain distinct. The allowance is max(0, min(uncommitted cash, remaining cap)). Reservations reduce each limiting constraint once; those constraints are compared with min rather than subtracted from each other. No payment or settlement endpoint exists. Cap usage is an explicit stored input; this demo period has no automatic calendar rollover.

## Shopping

A bounded explicit workflow loads context, retrieves the selected catalog category, checks complete deterministic merchant quotes, hard-filters constraints, sorts eligible results by total, and requests review. The goal is descriptive; category and spending limit are structured controls. No model execution or general chat understanding is claimed.

Imported email is untrusted evidence. The demo parser reads labeled fields and preserves unknowns. The local merchant maintains independent canonical code terms. It rejects unknown, expired, restricted, below-threshold, mismatched, or excluded offers; only one offer is applied. A quote uses the same product and quantity as its baseline, integer discount math, 9% tax on discounted merchandise, and the stored per-order shipping charge. Missing tax/shipping prevents execution.

Approval is bound to a persisted proposal ID and SHA-256 digest of exact terms, versions, budget context, and expiry. Execution revalidates the merchant's current quote, stock, approval, context, and expiry. A deterministic action key and unique owned key, inside the serialized transaction, prevent duplicate carts and reservations. Removal releases the reservation and restores stock in one transaction, once. Re-executing a removed action returns the removed action; it does not recreate a cart.

These guarantees apply to the local transactional merchant. They are not a claim of exactly-once execution for arbitrary remote APIs.

## Utilities and evidence

Source hashes deduplicate identical text. Sources retain raw text, ingestion metadata, content hashes, and versions. Bill imports first produce a confirmation form; only confirmation changes commitments. Provider/account/invoice identity chooses one obligation. Corrections save prior bill versions in bill_history. Comparable service-period lengths determine whether an amount/percentage comparison is meaningful.

Confirmation updates the owned budget version and creates/updates a stable review card. A historical paid bill is used for comparison only. Autopay scheduled is always unpaid. Acknowledging a review card does not alter cash or bill status.

The synthetic fixture clock can be fixed with DEMO_NOW (an ISO timestamp with offset). Otherwise dates are generated relative to UTC at seed time. Reset regenerates dates; persisted expired offers stay expired.

## Background work

review_due_tasks checks a bounded set of queued tasks, near-due unpaid bills, and relevant current offers for saved shopping tasks. It creates deduplicated next-action cards and a durable run record. It cannot approve or create a cart. /api/guild/scan uses a server-only bearer token. No remote Guild execution or schedule is claimed without a verified run.

## Privacy and limits

No raw source text, account fields, balances, or full goals belong in analytics. Provider adapters have explicit modes. INTEGRATIONS_ENABLED=false selects an offline demo for verification. Configured live evidence failures do not silently become fixture successes.

The local app uses one fixed synthetic user and loopback binding. Production authentication, multi-user authorization, merchant reconciliation, file/OCR processing, and long-term schema evolution are future work. JSON payload validation currently occurs at input/creation boundaries; a production migration plan should add stricter persisted record migrations and indexed operational columns before scaling.

## Intent refinement

Intent.decide evaluates complete eligible quotes against a persisted target total and urgency. Buy permits exact-quote proposal preparation; Wait and Skip cannot create a proposal. prepare additionally checks the selected product and quantity against the target, so selecting a more expensive candidate cannot bypass the decision.

watch_items stores user/task/product identity, target, urgency, last result, freshness versions, and next check. price_history stores timestamped seeded sample item prices. History is illustrative evidence only, never a forecast. Watch scans re-evaluate the same merchant, budget and evidence services. Completed/approved tasks are not rewritten by a watch scan; changing quote/context versions still invalidates executable proposals.

The Guild endpoint requires a backend bearer token and a stable platform run ID. A deterministic owned run key deduplicates redelivery. It only invokes the shared scan and returns compact task outcomes; it exposes no approval or spending tool. Hosting and schedule installation remain pending.

Statsig's gate decision is stored at task creation. SIE only ranks already eligible candidates when that stored gate is true. Current imports use deterministic labeled-text parsing, not SIE extraction.

Audit events and safe analytics metadata commit together. Best-effort SDK enqueue hooks run after commit. Amplitude AI records actual measured domain-tool durations without raw input/output. Product insert IDs are stable; this is not a guaranteed-delivery telemetry queue. Product retrieval, claim checks, relevance scoring, and watch evidence retrieval run outside write transactions. Product and preference snapshots are checked again before committing their results.

## Required product claims

Candidate responses separate retrieved information from a required-claim verification record and proposal_allowed. The record binds the concrete feature/claim, product fingerprint/version, retrieved evidence fingerprint, supporting evidence fingerprint, provider verdict, check ID, and source/version identifiers. checked_at is preserved from the provider; evaluated_at records the app's evaluation time. No check timestamp or ID is fabricated when the provider has not checked a claim.

Preparation, approval and execution perform fresh checks outside their write transactions, then validate the product snapshot under the transaction. Approval/execution require the claim and evidence binding to match the proposal's exact terms; changed evidence requires a new proposal. An already committed action remains idempotently replayable. Unsupported, conflicting, pending, not-verifiable and error results cannot authorize essential live claims, including direct API requests and watch refreshes.

Live fact-check access was not established within the experiment timebox. The current Senso adapter deliberately returns not_verifiable rather than deriving support from search results. Retrieval is still displayed accurately, and the explicit offline fixture mode retains the cart demonstration. See SENSO_LIVE_ACCESS.md and SENSO_VERIFICATION.md for the distinction between live observations and controlled test verdicts.
