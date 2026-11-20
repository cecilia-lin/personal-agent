# Remaining work

The local Intent app is runnable. See [the shared plan](docs/PLAN.md) for team ownership and [verification](docs/VERIFICATION.md) for exact claims.

1. Guild: run scripts/Guild.ps1 auth login when ready (sign-in deferred); obtain a deployed/reachable backend exposing only the authenticated tool, import docs/guild/openapi.json, connect its bearer credential, and create the coordinator. Verify one manual UI-closed watch/reminder run and redelivery before choosing a recurring schedule.
2. Statsig: confirm/create enable_reranker and its default-false rule. Existing tasks retain their stored assignment; create a new task to test a changed flag.
3. Amplitude: verify product events and Agent Analytics sessions in the intended project dashboard. HTTP acceptance alone is not dashboard visibility.
4. SingleStore: TLS SQL access, schema migration, and isolated live transaction checks passed. The local demo still selects SQLite. Decide whether to migrate its existing records and switch DB_BACKEND before a hosted deployment.
5. SIE: implement typed promotion/bill extraction with a confirmed hosted model; verify generation/tool-calling before adding a bounded coordinator. Current extraction remains deterministic text parsing. OCR is unsupported.
6. Senso: extend the verified product/policy corpus to additional sample catalog items if the team wants all candidates supported in live evidence mode. Current Arc retrieval was verified.
7. Cognee: key and workspace access are verified. Define which explicit preferences belong in memory, then implement scoped remember/recall and deletion; the current app has only an interface and a connection diagnostic.

Deferred by product scope: merchant negotiation, live historical-price integrations, price-fall predictions, real checkout/payment, banking, investment/portfolio work, Gmail OAuth, and external notifications.

Production identity, deployment access control for all routes, multi-user product behavior, comprehensive operational monitoring, and provider transaction parity require further work before exposing this local demo as a public app.
