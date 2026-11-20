# Verification — November 20, 2026

## Local checks actually run

- 33 Python tests passed using isolated temporary SQLite databases and disabled external credentials.
- TypeScript check and Vite production build passed.
- Actual HTTP smoke: bill confirmation/reimport, allowance change, promotion-aware approved cart, duplicate execution, removal/release, and bounded scan passed.
- Browser walkthrough: utility confirmation changed the allowance; exact HOME15 quote created a demo cart after approval and removal restored the reservation once.
- Browser Intent walkthrough: flexible urgency + $70 target yielded Wait for $82.46, saved a watch, displayed four dated sample observations, and recorded a check with no cart.
- Browser Buy walkthrough: now urgency + $90 target yielded Buy, exact approval created an $82.46 demo cart, and removal restored the $164 allowance.
- Restart tests retained tasks, audit, and watch state. Duplicate authenticated Guild run IDs return the same stored outcome.
- Tests verify hard limits, unknown charges, stale quotes/bills/budgets/preferences, ownership, competing reservations, promotion restrictions, bill revisions, flag persistence, and analytics privacy.

![Verified Intent watchlist](screenshots/intent-watchlist.jpg)

## Live provider checks

Initial provider checks at 2026-11-20 20:58 UTC, followed by SingleStore and Cognee setup checks in the same development session. All used private local configuration. Credentials and raw provider logs are excluded from Git.

| Integration | Observed result | What this does not prove |
|---|---|---|
| Senso | Organization access and matching product context retrieval succeeded; passage includes source/version identifiers | Full catalog coverage, historical prices, or merchant eligibility |
| Superlinked SIE | Account model catalog returned 54 entries; Qwen/Qwen3-Reranker-0.6B scored two synthetic products successfully | Extraction, generation, OCR, or automatic tool execution |
| Statsig | Server Core initialized with ready configuration; enable_reranker evaluated false, no matching rule ID | Gate creation, dashboard exposure visibility, or an experiment result |
| Amplitude | App-produced task_started accepted with SDK HTTP status 200; CLI reported recent traffic in the selected US project | CLI result is project-wide, not attribution to a specific event; dashboard/session visibility remains unchecked |
| SingleStore | Management access, TLS SQL login, dedicated personal_agent schema, and isolated live transaction checks passed | Existing app data remains in SQLite; no migration or production load test was performed |
| Guild | Official CLI 0.32.0 launcher verified; authenticated local handler and redelivery tests pass | Browser sign-in deferred by user; no hosted run, coordinator, or schedule |
| Cognee | API key accepted; current workspace URL discovered; authenticated datasets endpoint returned HTTP 200 | No memory ingestion, recall, or app memory adapter is enabled |

SingleStore checks covered owner isolation, rollback without callbacks, optimistic conflicts, a large Unicode document, concurrent duplicate cart execution, rejection of a competing stale proposal, one action/reservation, one-time allowance release, bill deduplication, scan redelivery and state read by a new service instance. All test records were removed using their unique owner ID. The first run exposed a real 64 KiB TEXT limit; widening payload columns to LONGTEXT fixed the full task flow. The local suite was rerun afterward: 33 tests and the frontend build passed.

The app can use live evidence and optional ranking while all money, merchant actions, and seeded price observations remain synthetic. Runtime status reports the current process, not a permanently cached success from this report.
