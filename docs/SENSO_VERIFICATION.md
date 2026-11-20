# Senso repairability verification

## Automated acceptance

On November 20, 2026, all 22 cases in `apps/api/tests/test_claim_verification.py` passed using isolated SQLite databases, a stubbed Senso provider, and a mocked HTTP failure through the actual adapter. These tests exercise the app's real HTTP endpoints, persistence, money rules, proposal approvals, and demo merchant. The Senso verdicts in this section are controlled test inputs, not evidence of live Senso access or real product certification. Together with the adapter's four tests, 26 targeted cases passed.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests/test_claim_verification.py -q
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

Live Senso capability and any organization-specific access limitation must be recorded separately from these automated results. Context retrieval alone is not a successful fact-check.
