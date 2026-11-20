# API contracts

Interactive endpoints use the fixed local demo-user. A different X-Demo-User is rejected. APP_MODE=live blocks these demo operations until production identity and live domain adapters exist.

| Method | Route | Effect |
|---|---|---|
| GET | /api/health | Readiness and actual DB connectivity |
| GET | /api/integrations | Per-adapter status |
| GET | /api/dashboard | Owned context, bills, offers, tasks, carts, next actions |
| POST | /api/demo/seed or /api/demo/reset | Idempotent seed / explicit demo-owned reset |
| POST | /api/imports/email | text, filename (.txt/.eml), optional subject/sender; persist source and extracted offer |
| POST | /api/imports/bill | text, filename (.txt); persist confirmation draft only |
| POST | /api/imports/bill/{id}/confirm | provider, account_ref, invoice_id, period_start/end, amount_minor, currency=USD, due_at, status |
| GET | /api/bills/{id}/history | Current and previous bill versions |
| GET | /api/sources/{id} | Owned stored evidence |
| POST | /api/tasks | goal, category, optional max_price_minor, target_price_minor, urgency=now/soon/flexible |
| POST | /api/tasks/{id}/run | Bounded explicit workflow |
| GET | /api/tasks/{id} | Progress, checkpoints, proposals, actions, audit |
| POST | /api/tasks/{id}/proposals | product_id, quantity; persist exact complete quote |
| POST | /api/proposals/{id}/decision | decision=approve/reject and exact terms_digest |
| POST | /api/proposals/{id}/execute | Revalidate and create/return one demo cart |
| GET | /api/actions/{id} | Persisted cart/result |
| POST | /api/actions/{id}/remove | Remove cart and release reservation once |
| POST | /api/next-actions/{id}/acknowledge | Acknowledge review only |
| POST | /api/background/scan | Bounded manual local scan, limit 1–10 |
| POST | /api/guild/scan | Same handler, server-only bearer token; required guild_run_id and optional limit |
| GET | /api/guild/openapi.json | Only the authenticated background operation |
| PATCH | /api/demo/budget, /bills/{id}, /products/{id}, /preferences | Synthetic development inputs; versioned updates |

See /api/docs for typed request schemas and /api/openapi.json for generated OpenAPI. All mutation responses include the persisted entity, rather than a fabricated success flag. Domain failures return an actionable detail with 409; invalid request schemas use 422. Failed/unconfigured live mode returns 503.

Example exact approval:

```json
{"decision":"approve","terms_digest":"<64-character digest from the persisted proposal>"}
```

An approved=true flag is not an approval contract. HTTP retries of approval/execution cannot duplicate the demo action. The import confirmation is an explicit approval of extracted utility fields, separate from shopping approval.

## Intent additions

| Method | Route | Effect |
|---|---|---|
| POST | /api/tasks/{id}/watch | Persist one active watch for the task; optional eligible product_id |
| GET | /api/watchlist | Owned persisted watches, including archived records |
| POST | /api/watchlist/{id}/archive | Idempotent archive |
| GET | /api/products/{id}/history | Timestamped seeded sample observations with provenance notice |

Task checkpoints include recommendation with decision=Buy/Wait/Skip, reason, basis, and prediction=null. Only Buy can prepare a proposal. A target is a complete quote total, distinct from the item prices in sample history. Scan responses include watchlist_checked and the persisted run_id.
