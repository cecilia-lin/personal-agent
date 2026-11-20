# Remaining work

The local Intent app is runnable. See [the shared plan](docs/PLAN.md) for team ownership and [verification](docs/VERIFICATION.md) for exact claims.

1. Guild: obtain authorized workspace access and a deployed/reachable backend exposing only the authenticated tool; import docs/guild/openapi.json, connect its bearer credential, create the coordinator and a schedule, then verify a UI-closed watch/reminder run and redelivery.
2. Statsig: confirm/create enable_reranker and its default-false rule. Existing tasks retain their stored assignment; create a new task to test a changed flag.
3. Amplitude: verify product events and Agent Analytics sessions in the intended project dashboard. HTTP acceptance alone is not dashboard visibility.
4. SingleStore: provide database credentials, run the generated migration, and repeat owner-isolation, bill-deduplication, and concurrent reservation checks against that backend.
5. SIE: implement typed promotion/bill extraction with a confirmed hosted model; verify generation/tool-calling before adding a bounded coordinator. Current extraction remains deterministic text parsing. OCR is unsupported.
6. Senso: extend the verified product/policy corpus to additional sample catalog items if the team wants all candidates supported in live evidence mode. Current Arc retrieval was verified.

Deferred by product scope: merchant negotiation, live historical-price integrations, price-fall predictions, real checkout/payment, banking, investment/portfolio work, Gmail OAuth, and external notifications.

Production identity, deployment access control for all routes, multi-user product behavior, comprehensive operational monitoring, and provider transaction parity require further work before exposing this local demo as a public app.
