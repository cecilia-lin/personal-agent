"""Upload the fictional desk-light spec sheets to Senso and fact-check the answer key live.

Usage (from the repo root, SENSO_API_KEY in the root .env or the environment):
    python scripts/senso_corpus_check.py --upload   # first time: upload docs, then check
    python scripts/senso_corpus_check.py            # re-run checks only (no duplicate uploads)
    python scripts/senso_corpus_check.py --runs 1   # quicker single pass

Uses the documented endpoints from https://docs.senso.ai/specs/sdk-api.yaml:
    POST /org/kb/raw          create a raw-text document (202, async ingestion)
    GET  /org/content/{id}    poll processing_status until complete
    POST /org/evals/text      kb_accuracy fact-check (wait=true, falls back to polling)
    GET  /org/evals/runs/{id} poll a queued run

Only fictional product text leaves the machine. Results go to .local/senso-corpus-check.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "fixtures" / "senso"
BASE_URL = "https://apiv2.senso.ai/api/v1"
DOCS = ["arc-light", "fold-light", "halo-light", "mini-light"]

# Mirrors fixtures/senso/senso_answer_key.md
CASES = [
    ("arc-light", "Arc desk light has a replaceable bulb.", "verified"),
    ("fold-light", "Fold task light has a replaceable light module.", "conflict"),
    ("halo-light", "Halo studio light has serviceable components.", "verified"),
    ("halo-light", "Halo studio light has a replaceable bulb.", "not_verifiable"),
    ("mini-light", "Mini LED light has a replaceable bulb.", "conflict"),
]
FINISHED = {"completed", "gated", "failed"}


def api_key():
    key = os.getenv("SENSO_API_KEY", "").strip()
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SENSO_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("Set SENSO_API_KEY in the root .env (or the environment) first.")
    return key


def upload(client):
    uploaded = {}
    for product in DOCS:
        path = CORPUS / f"{product}_spec_v1.md"
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        r = client.post("/org/kb/raw", json={"title": title, "text": text})
        r.raise_for_status()
        body = r.json()
        uploaded[product] = {"content_id": body["id"], "version_id": body.get("latest_content_version_id"),
                             "kb_node_id": body.get("kb_node_id"), "title": title}
        print(f"  uploaded {path.name} -> content {body['id']}")
    print("  waiting for ingestion...")
    deadline = time.time() + 300
    pending = set(uploaded)
    while pending and time.time() < deadline:
        for product in list(pending):
            r = client.get(f"/org/content/{uploaded[product]['content_id']}")
            r.raise_for_status()
            status = r.json().get("processing_status")
            if status == "complete":
                uploaded[product]["version_id"] = r.json().get("latest_content_version_id")
                pending.discard(product)
                print(f"  ingested {product}")
            elif status == "failed":
                sys.exit(f"Ingestion failed for {product}: {r.json().get('error_code')}")
        if pending:
            time.sleep(5)
    if pending:
        sys.exit(f"Ingestion still pending after 5 minutes: {sorted(pending)}")
    return uploaded


def fact_check(client, claim, label):
    r = client.post("/org/evals/text", json={
        "text": claim, "evaluator": "kb_accuracy", "wait": True, "label": label,
    }, timeout=httpx.Timeout(90, connect=10))
    r.raise_for_status()
    run = r.json()
    deadline = time.time() + 180
    while run.get("status") not in FINISHED and time.time() < deadline:
        time.sleep(4)
        r = client.get(f"/org/evals/runs/{run['eval_run_id']}")
        r.raise_for_status()
        run = r.json()
    return run


def summarize(run):
    claims = run.get("claims") or []
    first = claims[0] if claims else {}
    evidence = first.get("evidence") or []
    return {
        "eval_run_id": run.get("eval_run_id"), "status": run.get("status"),
        "verdict": first.get("verdict") or ("(no claim)" if run.get("status") == "completed" else run.get("status")),
        "quote": first.get("quote"), "reasoning": first.get("reasoning"),
        "confidence": first.get("confidence"), "grounding_failed": first.get("grounding_failed"),
        "evidence": [{k: e.get(k) for k in ("content_id", "content_version_id", "relation")} for e in evidence],
        "claims_found": len(claims), "error": run.get("error_message"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help="upload the 4 spec sheets first")
    parser.add_argument("--runs", type=int, default=3, help="repetitions per claim (default 3)")
    args = parser.parse_args()

    out_path = ROOT / ".local" / "senso-corpus-check.json"
    out_path.parent.mkdir(exist_ok=True)
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}

    with httpx.Client(base_url=BASE_URL, headers={"X-API-Key": api_key()},
                      timeout=httpx.Timeout(30, connect=5)) as client:
        r = client.get("/org/me")
        r.raise_for_status()
        print("Senso organization reachable.")
        docs = upload(client) if args.upload else previous.get("documents", {})
        if not docs:
            print("No upload record found; run with --upload if the docs aren't in Senso yet.")

        id_to_product = {d["content_id"]: p for p, d in docs.items()}
        results, all_pass = [], True
        for product, claim, expected in CASES:
            runs = []
            for i in range(args.runs):
                try:
                    runs.append(summarize(fact_check(client, claim, f"desk-light-{product}-{i + 1}")))
                except httpx.HTTPError as exc:
                    runs.append({"verdict": "service_error", "error": type(exc).__name__})
            verdicts = [r["verdict"] for r in runs]
            stable = len(set(verdicts)) == 1
            ok = stable and verdicts[0] == expected
            all_pass &= ok
            sources = {id_to_product.get(e["content_id"], e["content_id"] or "?")
                       for r in runs for e in r.get("evidence", [])}
            results.append({"product": product, "claim": claim, "expected": expected,
                            "verdicts": verdicts, "stable": stable, "pass": ok,
                            "evidence_from": sorted(sources), "runs": runs})
            print(f"\n{'PASS' if ok else 'FAIL'}  {claim}\n  expected {expected}, got {verdicts}"
                  f"\n  evidence from: {sorted(sources) or 'none'}"
                  f"\n  quote: {runs[0].get('quote') or '-'}")

    out_path.write_text(json.dumps({"documents": docs, "results": results,
                                    "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                   indent=2), encoding="utf-8")
    print(f"\n{'ALL PASS' if all_pass else 'SOME CHECKS FAILED'} — details in {out_path.relative_to(ROOT)}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        # Never print the key; body is safe to show for debugging the contract.
        print(f"Senso returned HTTP {exc.response.status_code} for {exc.request.method} {exc.request.url.path}:"
              f" {exc.response.text[:300]}")
        raise SystemExit(1)
