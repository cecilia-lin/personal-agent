# Guild: watchlist checks and utility reminders

Deployment status: pending. The local operation and authenticated contract are complete; no platform execution is claimed.

## Backend boundary

Expose only POST /api/guild/scan through an authenticated HTTPS reverse proxy. Keep the rest of the fixed-user demo API private. Guild cannot reach loopback. Set BACKGROUND_TOOL_TOKEN privately on the backend and install the corresponding bearer credential in the Guild custom integration.

Inputs: limit (1–10, default 5) and guild_run_id (required stable platform run ID, 1–128 letters/digits/underscore/dot/colon/hyphen). Retrying a platform run must reuse that ID.

The handler rechecks quotes, watch targets, urgency, current allowance, unpaid bills, and relevant offers. It persists next-action cards and a run record. It has no cart-execution tool. A response's guild_run_id is a caller-supplied correlation ID; it alone is not proof of a hosted Guild run.

Import the self-contained openapi.json in this folder. It contains one operation, review_due_tasks. The portal credential must generate Authorization: Bearer <token>; do not place the token in the schema.

## Configure in Guild

1. Use an existing authorized workspace. Create a custom HTTP integration whose base URL is the reachable backend origin.
2. Choose the documented bearer/API-key header authentication configuration, import openapi.json, build a version, publish it within the intended workspace, and install its credential.
3. Create one coordinator using coordinator.md. Give it only the review_due_tasks operation.
4. Create an API/manual trigger in the portal for an immediate test. Configure one hourly or daily time trigger; confirm its timezone in the portal.
5. Pass the actual platform run/session ID into guild_run_id. Reuse the ID on transport retries.

Optional CLI examples after account, workspace, URL, and auth are configured:

```sh
guild integration operation create <org>~intent --openapi ./docs/guild/openapi.json
guild integration version build <org>~intent --version-number 1.0.0
guild integration version publish <org>~intent --version-number 1.0.0
guild trigger create --type time --frequency DAILY --time 09:00 --agent intent-review
```

Use the portal-generated trigger/auth details; do not invent trigger endpoints. Account API keys support time-trigger creation, not API-trigger creation.

## Verification that remains

Save a Wait watch and a due utility bill. Close the app UI, invoke the Guild trigger, then reopen Home/Watchlist. Confirm the check timestamp, next-action card, backend run ID and actual Guild run ID. Redeliver the same run and confirm one stored outcome and no new reservation. Record the platform run link and time in VERIFICATION.md only after observing it.

References: [custom integrations](https://docs.guild.ai/services/create-an-integration), [schedules](https://docs.guild.ai/platform/schedule-triggers).
