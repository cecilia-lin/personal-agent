"""Publish only four fictional specs, then check the shared live runtime contract.

--upload-only publishes or reuses identical documents and confirms readiness.
Without upload flags this reconciles existing sources and repeats checks only.
The local answer key is never read or uploaded by this program.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.preparation.senso_publish import SensoPublisher, SensoJobError, timestamp

CORPUS = ROOT / "fixtures/senso"
SCHEMA = "intent-senso-corpus-v1"
NAMESPACE = "intent-desk-light-spec-v1"
DOCS = ("arc-light", "fold-light", "halo-light", "mini-light")
LEDGER = ROOT / ".local/senso-corpus-ledger.json"
RESULTS = ROOT / ".local/senso-corpus-check.json"
CASES = (
    ("arc-light", "Arc desk light", "replaceable_bulb", "has a replaceable bulb", "supported"),
    ("fold-light", "Fold task light", "replaceable_light_module", "has a replaceable light module", "conflict"),
    ("halo-light", "Halo studio light", "serviceable_components", "has serviceable components", "supported"),
    ("halo-light", "Halo studio light", "replaceable_bulb", "has a replaceable bulb", "unsupported"),
    ("mini-light", "Mini LED light", "replaceable_bulb", "has a replaceable bulb", "conflict"),
)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


@contextmanager
def exclusive_run(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("Corpus job lock exists; reconcile the prior process before another run") from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def documents():
    output = {}
    for product_id in DOCS:
        text = (CORPUS / f"{product_id}_spec_v1.md").read_text(encoding="utf-8")
        if f"Product ID: {product_id}" not in text or "Fictional demo data" not in text:
            raise ValueError("Corpus spec lacks its fictional label or product identity")
        output[product_id] = {"source_id": product_id, "title": text.splitlines()[0].lstrip("# "),
                              "text": text, "content_hash": digest(text), "source_version": digest(text),
                              "schema_version": SCHEMA}
    return output


def load_ledger(path):
    if not path.exists():
        return {"schema_version": SCHEMA, "namespace": NAMESPACE, "products": {}, "created_at": timestamp()}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SCHEMA or value.get("namespace") != NAMESPACE:
        raise ValueError("Unexpected corpus ledger schema or namespace")
    return value


def find_exact_source(publisher, document):
    """Bounded read-only reconciliation; never change text to evade duplicates."""
    status, found = publisher._request("GET", "/org/kb/find", params={"q": document["title"], "limit": 20})
    if status != 200 or not isinstance(found, dict) or not isinstance(found.get("nodes"), list):
        raise SensoJobError("Could not reconcile existing sources before upload")
    matches = []
    for node in found["nodes"][:5]:
        if not node.get("content_id") or not node.get("kb_node_id"):
            continue
        code, body = publisher._request("GET", f"/org/kb/nodes/{node['kb_node_id']}/content")
        if code == 200 and isinstance(body, dict) and isinstance(body.get("text"), str) and digest(body["text"]) == document["content_hash"]:
            matches.append({"content_id": node["content_id"], "kb_node_id": node["kb_node_id"],
                            "version_id": body.get("latest_content_version_id"), "version_num": body.get("version_num")})
    if len(matches) > 1:
        raise SensoJobError("Multiple exact corpus documents exist; explicit reconciliation is required")
    return matches[0] if matches else None


def bind_current_version(publisher, entry, document):
    """Confirm body and readiness, then bind a UUID from scoped retrieval."""
    code, body = publisher._request("GET", f"/org/kb/nodes/{entry['kb_node_id']}/content")
    if (code != 200 or not isinstance(body, dict) or body.get("id") != entry["content_id"]
            or not isinstance(body.get("text"), str) or digest(body["text"]) != document["content_hash"]):
        return {**entry, "status": "blocked", "error": "Remote corpus body or identity differs from approved local spec"}
    if body.get("processing_status") != "complete":
        return {**entry, "status": "pending", "error": "Corpus content is not fully processed"}
    code, response = publisher._request("POST", "/org/search/context", json={
        "query": f"Product {document['source_id']}: {document['title']}. Repair and parts.",
        "content_ids": [entry["content_id"]], "require_scoped_ids": True, "max_results": 3})
    passages = response.get("results", []) if code == 200 and isinstance(response, dict) else []
    matching = [p for p in passages if isinstance(p, dict) and p.get("content_id") == entry["content_id"]
                and p.get("version_id") and p.get("content_chunk_id") and isinstance(p.get("chunk_text"), str)]
    versions = {p["version_id"] for p in matching}
    if len(versions) != 1 or (entry.get("version_id") and entry["version_id"] not in versions):
        return {**entry, "status": "pending", "error": "Scoped retrieval has no single matching approved version"}
    return {**entry, "version_id": versions.pop(), "version_num": body.get("version_num"),
            "status": "ready", "body_verified_at": timestamp(), "retrieval_checked_at": timestamp()}


def prepare(publisher, ledger, path, *, allow_upload, max_wait_seconds=60):
    for product_id, document in documents().items():
        def checkpoint(entry):
            ledger["products"][product_id] = {**entry, "source_path": f"fixtures/senso/{product_id}_spec_v1.md"}
            ledger["updated_at"] = timestamp()
            save(path, ledger)

        existing = ledger["products"].get(product_id)
        if existing and existing.get("content_hash") != document["content_hash"]:
            raise ValueError("Local spec changed after publication; reconcile its version explicitly")
        if existing and existing.get("status") == "not_uploaded":
            existing = None
        if not existing or not existing.get("content_id"):
            duplicate = find_exact_source(publisher, document)
            if duplicate:
                existing = {**{k: v for k, v in document.items() if k != "text"}, **duplicate,
                            "namespace": NAMESPACE, "status": "processing", "reused_exact_source": True,
                            "created_at": timestamp()}
                checkpoint(existing)
            elif existing:
                checkpoint({**existing, "status": "ambiguous", "error": "No exact source found yet; upload was not repeated"})
                continue
            elif not allow_upload:
                checkpoint({**{k: v for k, v in document.items() if k != "text"}, "namespace": NAMESPACE,
                            "status": "not_uploaded", "error": "Run --upload-only to publish this fictional spec"})
                continue
        entry = publisher.publish(document, existing, checkpoint=checkpoint)
        if entry.get("content_id") and entry.get("kb_node_id"):
            entry = publisher.wait_ready(entry, max_wait_seconds=max_wait_seconds,
                                         checkpoint=lambda value: checkpoint({**value, "status": "processing"}
                                                                             if value.get("status") == "ready" else value))
            if entry.get("status") == "ready":
                try:
                    entry = bind_current_version(publisher, entry, document)
                except SensoJobError as exc:
                    entry = {**entry, "status": "pending", "error": str(exc)}
                if entry["status"] == "ready":
                    entry.pop("error", None)
            checkpoint(entry)
        print(json.dumps({"product_id": product_id, "status": ledger["products"][product_id]["status"]}), flush=True)
    return all(ledger["products"].get(p, {}).get("status") == "ready" for p in DOCS)


def check(api_key, ledger_path, runs, output):
    from app.integrations.senso import SensoEvidenceProvider
    provider = SensoEvidenceProvider(api_key, ledger_path=ledger_path)
    results = {"schema_version": SCHEMA, "checked_at": timestamp(), "results": []}
    try:
        for product_id, name, feature, suffix, expected in CASES:
            case = {"product": product_id, "claim": f"{name} {suffix}.", "expected_state": expected, "runs": []}
            for _ in range(runs):
                result = provider.verify_claim({"id": product_id, "name": name}, case["claim"], feature)
                case["runs"].append(result)
                save(output, results | {"in_progress": case})
            states = [result.get("state") for result in case["runs"]]
            evidence = [json.dumps([{key: source.get(key) for key in
                         ("content_id", "content_chunk_id", "version_id", "source_version", "excerpt", "chunk_text")}
                         for source in result.get("sources", [])], sort_keys=True) for result in case["runs"]]
            stable = len(set(states)) == 1 and len(set(evidence)) == 1
            case.update(stable=stable, passed=stable and all(state == expected for state in states),
                        distinct_check_count=len({result.get("check_id") for result in case["runs"] if result.get("check_id")}),
                        repeat_mode="Idempotent input replay; repeated calls may reuse a completed evaluator run")
            results["results"].append(case)
            save(output, results)
            print(json.dumps({"product": product_id, "feature": feature, "expected": expected,
                              "states": states, "passed": case["passed"]}), flush=True)
    finally:
        provider.close()
    return all(case["passed"] for case in results["results"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true", help="publish/reuse specs before checking")
    parser.add_argument("--upload-only", action="store_true", help="publish/reuse specs and verify readiness")
    parser.add_argument("--dry-run", action="store_true", help="validate local specs without network")
    parser.add_argument("--runs", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--max-wait-seconds", type=int, choices=range(0, 91), default=60)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--output", type=Path, default=RESULTS)
    args = parser.parse_args()
    docs = documents()
    if args.dry_run:
        print(json.dumps({"documents": list(docs), "count": len(docs), "answer_key_uploaded": False}))
        return 0
    load_dotenv(ROOT / ".env")
    key = os.getenv("SENSO_API_KEY", "").strip()
    if not key:
        raise ValueError("SENSO_API_KEY is required in the environment or ignored root .env")
    with exclusive_run(args.ledger):
        ledger = load_ledger(args.ledger)
        publisher = SensoPublisher(key, NAMESPACE)
        try:
            ready = prepare(publisher, ledger, args.ledger, allow_upload=args.upload or args.upload_only,
                            max_wait_seconds=args.max_wait_seconds)
        finally:
            publisher.close()
        if not ready:
            return 2
        return 0 if args.upload_only or check(key, args.ledger, args.runs, args.output) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error_class": type(exc).__name__, "message": "Corpus check stopped. Inspect the local ledger; no credentials or remote bodies printed."}))
        raise SystemExit(1)
