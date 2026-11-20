# Guild: watchlist checks and utility reminders

Deployment status: pending. The local operation and authenticated contract are complete; no platform execution is claimed.

## CLI and SDK

The official CLI is `@guildai/cli`. The repository launcher reuses `guild` on PATH or runs pinned version 0.32.0 through npx (with a pnpm fallback). It does not add packages to the web app or Python environment.

```powershell
.\scripts\Guild.ps1 version
.\scripts\Guild.ps1 auth login
.\scripts\Guild.ps1 workspace list --mode json
```

Version 0.32.0 was executed successfully. Browser sign-in was started and then cancelled at the user's request; run `auth login` again when ready. Login state belongs to the CLI, not the app's `.env`; no Guild account API key is required for this route.

Guild also provides the TypeScript `@guildai/agents-sdk` for hosted agents. This app keeps its business logic in the Python handler below; a hosted coordinator uses its custom integration. No hosted SDK agent has been deployed yet.

## Backend boundary

Expose only POST /api/guild/scan through an authenticated HTTPS reverse proxy. Keep the rest of the fixed-user demo API private. Guild cannot reach loopback. Set BACKGROUND_TOOL_TOKEN privately on the backend and install the corresponding bearer credential in the Guild custom integration.

Inputs: limit (1–10, default 5) and guild_run_id (required stable platform run ID, 1–128 letters/digits/underscore/dot/colon/hyphen). Retrying a platform run must reuse that ID.

The handler rechecks quotes, watch targets, urgency, current allowance, unpaid bills, and relevant offers. It persists next-action cards and a run record. It has no cart-execution tool. A response's guild_run_id is a caller-supplied correlation ID; it alone is not proof of a hosted Guild run.

Import the self-contained openapi.json in this folder. It contains one operation, review_due_tasks. The portal credential must generate Authorization: Bearer <token>; do not place the token in the schema.

## Configure in Guild

1. Use an existing authorized workspace. Create a custom HTTP integration whose base URL is the reachable backend origin.
2. Choose the documented bearer/API-key header authentication configuration, import openapi.json, build a version, publish it within the intended workspace, and install its credential.
3. Create one coordinator using coordinator.md. Give it only the review_due_tasks operation.
4. Create an API/manual trigger in the portal for an immediate test. Add a recurring time trigger only after choosing its cadence and timezone.
5. Pass the actual platform run/session ID into guild_run_id. Reuse the ID on transport retries.

Optional CLI examples after account, workspace, URL, and auth are configured:

```powershell
# Substitute the authorized account and the actual HTTPS backend origin.
.\scripts\Guild.ps1 integration create intent --base-url https://YOUR-BACKEND --auth-scheme api-key
.\scripts\Guild.ps1 integration operation create ACCOUNT~intent --openapi ./docs/guild/openapi.json
.\scripts\Guild.ps1 integration version build ACCOUNT~intent --version-number 1.0.0
.\scripts\Guild.ps1 integration version publish ACCOUNT~intent --version-number 1.0.0
# Prompts for the backend bearer credential; do not put it in command history.
.\scripts\Guild.ps1 integration connect ACCOUNT~intent --owner ACCOUNT
```

Use the portal-generated trigger/auth details; do not invent trigger endpoints. Account API keys support time-trigger creation, not API-trigger creation.

## Verification that remains

Save a Wait watch and a due utility bill. Close the app UI, invoke the Guild trigger, then reopen Home/Watchlist. Confirm the check timestamp, next-action card, backend run ID and actual Guild run ID. Redeliver the same run and confirm one stored outcome and no new reservation. Record the platform run link and time in VERIFICATION.md only after observing it.

References: [CLI](https://www.guild.ai/product/cli), [SDK agents](https://docs.guild.ai/guide/coded-agents), [custom integrations](https://docs.guild.ai/services/create-an-integration), [schedules](https://docs.guild.ai/platform/schedule-triggers).
