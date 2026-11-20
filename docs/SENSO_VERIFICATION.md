# Senso product-claim verification

Live Senso evaluation now works with the configured organization. Five product-specific cases passed: Arc bulb supported, Fold module contradicted, Halo serviceable components supported, Halo bulb unsupported, and Mini bulb contradicted. Each was replayed three times with one idempotent check ID per claim. See [actual live evidence and IDs](SENSO_LIVE_ACCESS.md). These provider results are separate from controlled tests of application behavior below.

## Automated acceptance

On November 20, 2026, 45 targeted tests passed: 22 application claim-control tests, four existing adapter tests, and 19 documented evaluation-adapter tests. Application tests use isolated SQLite databases, a stubbed Senso provider, and mocked HTTP failures through the actual adapter. They exercise HTTP endpoints, persistence, money rules, approvals, and the demo merchant. Supplied verdicts are controlled inputs, separate from the live corpus results above. Tests inject their own source ledger instead of reading local live artifacts.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests/test_claim_verification.py apps/api/tests/test_senso_verification_adapter.py apps/api/tests/test_senso_live_eval.py -q
```

| Case | Observed application behavior |
|---|---|
| Supported required claim and affordable quote | Proposal created with product version, claim, check ID, source version, and evidence fingerprint; approved cart reserves funds once; duplicate execution returns the same action; removal releases funds once. |
| Conflict, unsupported, not_verifiable, pending, or service error | Proposal blocked for the Arc light even though the local catalog says repairable, stock is positive, the quote is $82.46, and allowance is $200. The negative therefore comes from the evidence check. |
| Retrieval succeeds but fact-check throws | Retrieved passage remains visible, verification is error, proposal is blocked, and private exception text is not returned to the shopper. |
| Actual Senso adapter receives HTTP 503 | Candidate explicitly reports a retrieval error and blocks direct proposal creation. |
| Supported verdict lacks check ID or source version | It cannot authorize a proposal. |
| Provider attempts to mark an essential requirement not_required | Server retains the requirement and blocks the unverified claim. |
| Fresh conflict at prepare, approve, execute, or repeated approval | Direct API calls cannot bypass the current claim gate; no action is created. |
| Source version changes after proposal | Even a fresh supported verdict requires a new proposal before approval or execution. |
| Replaceable-bulb claim changes to serviceable-components claim | Approval is rejected; these facts are not treated as interchangeable. |
| Product/source version changes during the remote check | Proposal creation is rejected because the checked product snapshot is stale. |
| Watch recheck returns conflict/error | Watch/task recommendation becomes blocked; an unchanged local quote does not hide a new verification error. |
| Legacy task contains retrieval without verification | Retrieved context alone cannot authorize a proposal. |
| Remote-call transaction boundary | Every stubbed retrieval and fact-check asserts that no database write transaction is active, including task runs, proposal/approval/execution refreshes, and watch scans. |

The 19 new adapter checks cover a wrong extracted claim, wrong subject, unapproved source/version, invented quote, grounding failure, negative verdicts, pending/service errors, a source changing during evaluation, completed-summary replay, missing-key fail-closed behavior, and distinct feature requirements. Actual version-bound evidence fingerprints use approved content ID, version UUID, body hash, and version number. A new check ID or another valid quote from an unchanged source does not alone invalidate approved terms; a source change still does.

The integration preserves native verdicts, check/claim IDs, quote, timestamp, evaluator version, and citation fields. If the evaluator omits its optional source version, the adapter verifies the unchanged approved body/version before and after evaluation and binds it to the UUID returned by scoped context retrieval. No missing native ID is manufactured.

The complete live shopper journey is recorded separately by the main acceptance run. A missing key or service failure keeps an honest live failure state; explicit fixture configuration is required for an offline demonstration. Context retrieval alone remains insufficient to authorize an essential claim.
