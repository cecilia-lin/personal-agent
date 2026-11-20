# Foundation review — November 20, 2026

Reviewed the teammate foundation at `b87c020` (`codex/intent-foundation`) before incorporating it into local `main`. The existing `apps/api` and `apps/web` architecture and dependency locks were retained. The earlier standalone scaffold is preserved in a local Git stash rather than merged as a second application.

## Fixed findings

| Finding | Effect before fix | Change |
| --- | --- | --- |
| Audit sorting used timestamp plus random UUID | A fixed `DEMO_NOW` shuffled executed steps; clock ties could show a recommendation check before task start | Add a monotonic, owner-scoped event sequence inside the serialized writer transaction and sort by it; legacy events retain timestamp fallback |
| Non-multipart MIME imports skipped content-type validation | HTML was accepted despite the plain-text contract; binary MIME bodies raised an unhandled `TypeError` | Parse `.eml` consistently, require a plain-text body, reject unsupported MIME types and decoding failures with 422; preserve multipart plain-text support |
| Whitespace satisfied required text lengths | Blank intentions, catalog categories, source imports and bill identities were accepted | Trim intention/identity fields before validation; reject blank source text while retaining original valid source content |

Regression tests reproduce the pre-fix failures and verify valid plain-text/MIME imports still work. New tests live in `apps/api/tests/test_foundation_review.py`; shared tests remain intact.

## Local setup improvements

- Added macOS/Linux setup, startup and verification scripts alongside the Windows scripts.
- Use the same Python and pnpm locks; preserve existing `.env` and database data.
- Added a GitHub Actions workflow that runs the same setup and verification commands on Linux.
- Documented startup, explicit offline mode and smoke testing in [LOCAL_MACOS.md](LOCAL_MACOS.md).

## Verification scope

The original 33 tests, frontend TypeScript check and production build passed before changes. All **45 tests** pass after adding 12 regression cases, and the frontend TypeScript check and production build pass. The actual HTTP smoke flow passed for bill confirmation/deduplication, eligible promotion, exact approval, idempotent cart execution and one-time reservation release. The frontend proxy successfully returned backend health. An isolated headless Chrome check opened Shopping at desktop and mobile widths with no page errors or horizontal mobile overflow; screenshots were inspected locally. The new GitHub Actions workflow has not yet run on GitHub.

The local review used Python 3.13 and the explicit demo mode with external integrations disabled. It did not reverify the teammate's live Senso, SIE, Statsig or Amplitude account checks. Those measurements remain documented separately in [VERIFICATION.md](VERIFICATION.md). Real model extraction/tool selection, hosted Guild execution, SingleStore transaction parity and production authentication remain outside this review.
