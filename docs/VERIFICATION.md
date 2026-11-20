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

Checked at 2026-11-20 20:58 UTC using private local configuration. Credentials and raw provider logs are excluded from Git.

| Integration | Observed result | What this does not prove |
|---|---|---|
| Senso | Organization access and matching product context retrieval succeeded; passage includes source/version identifiers | Full catalog coverage, historical prices, or merchant eligibility |
| Superlinked SIE | Account model catalog returned 54 entries; Qwen/Qwen3-Reranker-0.6B scored two synthetic products successfully | Extraction, generation, OCR, or automatic tool execution |
| Statsig | Server Core initialized with ready configuration; enable_reranker evaluated false, no matching rule ID | Gate creation, dashboard exposure visibility, or an experiment result |
| Amplitude | Safe synthetic product event accepted with SDK HTTP status 200 | Dashboard/session visibility; AI SDK tool delivery is separately checked locally |
| SingleStore | Adapter and generated rowstore DDL only | No live connection or transaction test: credentials absent |
| Guild | Authenticated local handler and redelivery tests pass | No hosted run, coordinator, or schedule: workspace/backend setup pending |

The app can use live evidence and optional ranking while all money, merchant actions, and seeded price observations remain synthetic. Runtime status reports the current process, not a permanently cached success from this report.
