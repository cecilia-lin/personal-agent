# Fictional desk-light evidence corpus

Only the four `*_spec_v1.md` files are eligible for upload. The answer key and this README remain local. The products are fictional and their specifications deliberately differ from some catalog assertions.

The Fold catalog says its light module is replaceable; the Fold spec explicitly says it is integrated and not user-replaceable. Keep that contradiction: it proves an otherwise eligible product can be blocked by Senso evidence. Halo's replaceable arm joints and power supply support serviceable components, but do not establish a replaceable bulb. The missing bulb claim is expected to be `unsupported`.

From the repository root, using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --dry-run
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --upload-only
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --runs 1
.\.venv\Scripts\python.exe scripts/senso_corpus_check.py --runs 3
```

The script loads the ignored root `.env`; it never prints the key. `--upload-only` discovers exact matching sources, checkpoints before a write, waits for actual node readiness, compares the remote body with the approved local hash, and binds its scoped retrieval version. Repeated runs reuse the ledger at `.local/senso-corpus-ledger.json`. A timeout or interrupted upload is reconciled without replaying an uncertain mutation. Changed source text requires explicit version reconciliation; the script does not edit, delete or overwrite existing sources.

Results and check IDs are saved to `.local/senso-corpus-check.json`. The runtime's documented `kb_accuracy` evaluation is separate from scoped context retrieval. The evaluator searches organization-wide, so the application checks its citations against the approved product source and version. Unresolved or unapproved evidence cannot authorize a proposal.

`--runs 3` checks repeatable application results, including evidence identities and passages. Idempotent evaluation inputs can reuse the same completed Senso run; `distinct_check_count` reports this explicitly. Replays are not three independent model evaluations.

In Shopping, choose the explicit required feature, set the time/price controls, and select Find options. Repairability checks the specific feature asserted for each product. The replaceable-bulb, replaceable-module and serviceable-components options are distinct requirements. The demo preserves exact quotes, budget calculations, approval review and cart reservations.
