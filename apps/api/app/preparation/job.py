"""Checkpointed preparation job. No application database writes or financial actions."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

SCHEMA = "intent-cognee-v1"
STAGES = ("fetch", "normalize", "enrich", "validate", "publish-senso", "ingest-cognee", "verify", "export-graph")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def content_hash(value):
    return hashlib.sha256((value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def stable_evidence(value):
    """Observation timestamps are not a new semantic source version."""
    if isinstance(value, dict):
        return {k: stable_evidence(v) for k, v in value.items() if k not in {"checked_at", "updated_at"}}
    if isinstance(value, list):
        return [stable_evidence(v) for v in value]
    return value


class PreparationJob:
    def __init__(self, output, *, max_products=6, enrich_products=6, max_model_calls=12,
                 concurrency=2, synthetic_owner="intent-demo", resume=False, dry_run=False):
        if not 1 <= max_products <= 24 or not 0 <= enrich_products <= 6 or not 0 <= max_model_calls <= 12 or not 1 <= concurrency <= 2:
            raise ValueError("Limits: products 1..24, enriched 0..6, model calls 0..12, concurrency 1..2.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{3,64}", synthetic_owner) or synthetic_owner == "demo-user":
            raise ValueError("Use an explicit isolated synthetic owner, never demo-user.")
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.path = self.output / "manifest.json"
        self.dry_run, self.resume = dry_run, resume
        config = dict(max_products=max_products, enrich_products=enrich_products, max_model_calls=max_model_calls,
                      concurrency=concurrency, synthetic_owner=synthetic_owner)
        if self.path.exists():
            if not resume:
                raise ValueError("Output already contains a job. Use --resume or a new output directory.")
            self.manifest = json.loads(self.path.read_text(encoding="utf-8"))
            if self.manifest["config"]["synthetic_owner"] != synthetic_owner:
                raise ValueError("A resumed job cannot change its synthetic owner.")
            if max_products > 6 and not self.manifest.get("smoke_verified"):
                raise ValueError("Complete six-product live ingestion and graph verification before expanding the job.")
            self.manifest["config"] = config
        else:
            if max_products > 6:
                raise ValueError("Start with --max-products 6, then expand using --resume.")
            self.manifest = {"schema_version": SCHEMA, "job_id": "intentprep_" + uuid4().hex[:12],
                             "created_at": stamp(), "config": config, "stages": {},
                             "senso_ledger": {}, "cognee_ledger": {}, "datasets": {}, "errors": [],
                             "specialist_model_calls": 0, "hosted_ingestion_model_usage": "unknown until returned"}
        self.checkpoint()

    def checkpoint(self):
        self.manifest["updated_at"] = stamp()
        save_json(self.path, self.manifest)

    def load(self, name):
        return json.loads((self.output / name).read_text(encoding="utf-8"))

    def run(self, stage):
        stages = STAGES if stage == "all" else (stage,)
        for current in stages:
            self.manifest["stages"][current] = {"state": "running", "started_at": stamp(), "dry_run": self.dry_run}
            self.checkpoint()
            try:
                result = getattr(self, current.replace("-", "_"))()
                self.manifest["stages"][current].update(state=result.get("state", "complete"), result=result, ended_at=stamp())
            except Exception as exc:
                # Provider errors can contain credentials or raw private response content.
                self.manifest["stages"][current].update(state="failed", error_class=type(exc).__name__, ended_at=stamp())
                self.manifest["errors"].append({"stage": current, "error_class": type(exc).__name__, "at": stamp()})
                self.checkpoint()
                raise
            self.checkpoint()
            brief = {k: v for k, v in self.manifest["stages"][current]["result"].items()
                     if not isinstance(v, (dict, list))}
            print(json.dumps({"stage": current, **brief}), flush=True)
            if self.manifest["stages"][current]["state"] in {"failed", "pending", "blocked"}:
                break
        return self.manifest

    def fetch(self):
        from app.preparation.catalog import fetch_snapshot
        snapshot = fetch_snapshot(self.output)
        self.manifest["source_snapshot"] = {k: v for k, v in snapshot.items() if k not in {"data", "products"}}
        return {"cached_snapshot": True}

    def normalize(self):
        from app.preparation.catalog import fetch_snapshot, normalize_snapshot
        result = normalize_snapshot(fetch_snapshot(self.output), self.manifest["config"]["max_products"])
        save_json(self.output / "normalized.json", result)
        self.manifest["accepted_records"] = len(result["products"])
        self.manifest["rejected_records"] = len(result["rejected"])
        return {"accepted": len(result["products"]), "rejected": len(result["rejected"]), "categories": result["categories"]}

    def enrich(self):
        from app.preparation.catalog import research_findings, synthetic_scenarios
        products = self.load("normalized.json")["products"]
        findings = research_findings(products[:self.manifest["config"]["enrich_products"]], self.manifest["job_id"])
        personas = synthetic_scenarios(products, findings, self.manifest["config"]["synthetic_owner"], self.manifest["job_id"])
        save_json(self.output / "research-findings.json", findings)
        save_json(self.output / "personas.json", personas)
        self.manifest["specialists"] = {"product_research": "deterministic_parser", "offer_policy": "source_retrieval_and_domain_checks",
                                       "scenario_memory": "deterministic_synthetic_fixture_generator",
                                       "model_enrichment": "pending: no supported SIE_GENERATION_MODEL configured"}
        return {"research_records": len(findings), "personas": len(personas), "specialist_model_calls": 0,
                "model_enrichment": "pending"}

    def validate(self):
        from app.preparation.catalog import product_document, normalize_snapshot, fetch_snapshot
        products = self.load("normalized.json")["products"]
        canonical = normalize_snapshot(fetch_snapshot(self.output), self.manifest["config"]["max_products"])
        if content_hash(canonical["products"]) != content_hash(products):
            raise ValueError("Normalized products differ from the cached source snapshot")
        ids = {p["product_id"] for p in products}
        if len(ids) != len(products) or not products:
            raise ValueError("Duplicate or empty product selection")
        if len(products) > self.manifest["config"]["max_products"]:
            raise ValueError("Normalized records exceed the selected bound")
        documents = []
        for product in products:
            if not product["research_only"] or product["executable_quote"] or product["application_product_id"] is not None:
                raise ValueError("Research data cannot become an executable catalog quote")
            text = product_document(product)
            documents.append({"source_id": product["product_id"], "source_version": product["source_version"],
                              "content_hash": content_hash(text), "schema_version": SCHEMA,
                              "title": self.manifest["job_id"] + " " + product["product_id"], "text": text})
        if len({d["content_hash"] for d in documents}) != len(documents):
            raise ValueError("Duplicate evidence documents")
        save_json(self.output / "documents.json", documents)
        save_json(self.output / "validation.json", {"accepted": len(documents), "rejected": self.load("normalized.json")["rejected"],
                                                    "state": "passed", "synthetic_owner": self.manifest["config"]["synthetic_owner"]})
        self.manifest["validated_artifacts"] = {name: content_hash(self.load(name)) for name in
                                               ("normalized.json", "documents.json", "research-findings.json", "personas.json")}
        if len(documents) == 6:
            self.manifest["smoke_validated"] = True
        return {"state": "complete", "validated_products": len(documents), "smoke_validated": self.manifest.get("smoke_validated", False)}

    def validated_documents(self):
        hashes = self.manifest.get("validated_artifacts", {})
        for name in ("normalized.json", "documents.json", "research-findings.json", "personas.json"):
            if name not in hashes or content_hash(self.load(name)) != hashes[name]:
                raise ValueError("Preparation artifacts changed or were not validated; rerun validate before publication")
        documents = self.load("documents.json")
        if not documents or len(documents) > self.manifest["config"]["max_products"]:
            raise ValueError("Publication records exceed the selected bound")
        if len({d["source_id"] for d in documents}) != len(documents):
            raise ValueError("Duplicate publication source IDs")
        return documents

    def publish_senso(self):
        from app.preparation.senso_publish import SensoPublisher, policy_findings
        documents = self.validated_documents()
        if self.dry_run:
            return {"state": "planned", "documents": len(documents), "remote_mutations": 0}
        if not os.getenv("SENSO_API_KEY"):
            return {"state": "blocked", "reason": "SENSO_API_KEY is missing"}
        publisher = SensoPublisher(os.environ["SENSO_API_KEY"], self.manifest["job_id"])
        ledger = self.manifest["senso_ledger"]
        def key_for(document):
            return content_hash([document["source_id"], document["content_hash"], document["schema_version"]])
        def checkpoint(key, entry):
            ledger[key] = entry
            self.checkpoint()
        try:
            for document in documents:
                key = key_for(document)
                publisher.publish(document, ledger.get(key), checkpoint=lambda e, k=key: checkpoint(k, e))
            # Uploads run before polling, so processing can proceed concurrently.
            for document in documents:
                key = key_for(document)
                publisher.wait_ready(ledger[key], max_wait_seconds=30,
                                     checkpoint=lambda e, k=key: checkpoint(k, e))
            products = {p["product_id"]: p for p in self.load("normalized.json")["products"]}
            findings, retrievals = [], []
            for document in documents[:self.manifest["config"]["enrich_products"]]:
                entry = ledger[key_for(document)]
                if entry["status"] != "ready":
                    continue
                passages = publisher.retrieve(entry, "What are the exact return policy, warranty and shipping statements for " + products[document["source_id"]]["title"] + "?")
                retrievals.extend(passages)
                findings.extend(policy_findings(products[document["source_id"]], entry, passages,
                                                 run_id=self.manifest["job_id"]))
            save_json(self.output / "senso-retrievals.json", retrievals)
            save_json(self.output / "policy-findings.json", findings)
            self.manifest["senso_artifact_hashes"] = {
                "senso-retrievals.json": content_hash(retrievals), "policy-findings.json": content_hash(findings)}
        finally:
            publisher.close()
        ready = sum(ledger[key_for(d)].get("status") == "ready" for d in documents)
        return {"state": "complete" if ready == len(documents) else "pending", "ready": ready,
                "documents": len(documents), "policy_checks": len(findings), "operation": "context_retrieval_and_deterministic_checks"}

    def cognee_batches(self):
        documents = self.validated_documents()
        policies = []
        if (self.output / "policy-findings.json").exists():
            for name in ("policy-findings.json", "senso-retrievals.json"):
                if self.manifest.get("senso_artifact_hashes", {}).get(name) != content_hash(self.load(name)):
                    raise ValueError("Senso artifacts changed or were not sealed after retrieval")
            policies = stable_evidence(self.load("policy-findings.json"))
        personas = self.load("personas.json")
        findings = self.load("research-findings.json")
        namespace = self.manifest["job_id"]
        batches = []
        for start in range(0, len(documents), 6):
            subset = documents[start:start + 6]
            ids = {d["source_id"] for d in subset}
            text = "Intent research-only sample catalog. No executable offers.\n\n" + "\n\n".join(d["text"] for d in subset)
            text += "\n\nProduct Research findings:\n" + json.dumps([f for f in findings if f["product_id"] in ids], sort_keys=True)
            text += "\n\nOffer/Policy findings from scoped Senso context retrieval (not a fact-check API):\n" + json.dumps([p for p in policies if p["product_id"] in ids], sort_keys=True)
            batches.append({"source_id": f"catalog-batch-{start // 6}", "dataset_key": "catalog",
                            "dataset_name": namespace + "_catalog", "text": text, "source_ids": sorted(ids)})
        known = {d["source_id"] for d in documents}
        for index, persona in enumerate(personas):
            if not persona.get("synthetic_demo") or not persona["id"].startswith(self.manifest["config"]["synthetic_owner"] + ":persona:"):
                raise ValueError("Persona is outside the isolated synthetic owner")
            if not set(persona["product_ids"]) <= known:
                raise ValueError("Persona references unknown products")
            records = persona["durable_records"]
            if any(not r.get("synthetic_demo") or r.get("scope") == "session_only" or r["owner"] != persona["id"] for r in records):
                raise ValueError("Only validated durable synthetic records may enter the graph")
            text = "PRIVATE SYNTHETIC DEMO PERSONA. Never represents the active household.\n"
            text += json.dumps(records, sort_keys=True, ensure_ascii=False)
            text += "\nProduct Research shared contribution:\n" + json.dumps([f for f in findings if f["product_id"] in persona["product_ids"]], sort_keys=True)
            text += "\nOffer/Policy shared contribution:\n" + json.dumps([p for p in policies if p["product_id"] in persona["product_ids"]], sort_keys=True)
            batches.append({"source_id": persona["id"], "dataset_key": persona["id"],
                            "dataset_name": namespace + "_persona_" + chr(97 + index), "text": text,
                            "source_ids": persona["product_ids"]})
        return batches

    def cognee_client(self):
        from app.integrations.cognee import CogneeClient
        names = {b["dataset_name"] for b in self.cognee_batches()}
        ids = {d["id"] for d in self.manifest["datasets"].values() if d.get("id")}
        return CogneeClient.from_env(allowed_datasets=names | ids)

    def ingest_cognee(self):
        from app.integrations.cognee import CogneeError
        batches = self.cognee_batches()
        if self.dry_run:
            return {"state": "planned", "durable_batches": len(batches), "remote_mutations": 0}
        if not os.getenv("COGNEE_API_KEY") or not os.getenv("COGNEE_BASE_URL"):
            return {"state": "blocked", "reason": "COGNEE_API_KEY and COGNEE_BASE_URL are required"}
        ledger = self.manifest["cognee_ledger"]
        with self.cognee_client() as client:
            for batch in batches:
                digest = content_hash(batch["text"])
                key = content_hash([batch["source_id"], digest, SCHEMA])
                dataset = self.manifest["datasets"].setdefault(batch["dataset_key"], {"name": batch["dataset_name"], "id": None})
                filename = batch["dataset_name"] + "_" + digest[:16] + ".txt"
                entry = ledger.get(key)
                if entry is None:
                    entry = {"source_id": batch["source_id"], "content_hash": digest, "schema_version": SCHEMA,
                             "dataset_name": batch["dataset_name"], "filename": filename, "status": "inflight", "created_at": stamp()}
                    ledger[key] = entry
                    self.checkpoint()
                    try:
                        response = client.remember(batch["text"], batch["dataset_name"], filename=filename,
                                                   metadata={"job_id": self.manifest["job_id"], "source_id": batch["source_id"],
                                                             "source_ids": batch["source_ids"], "content_hash": digest,
                                                             "schema_version": SCHEMA, "synthetic_demo": batch["dataset_key"] != "catalog"})
                        entry.update(status="accepted", response=response, accepted_at=stamp())
                    except CogneeError as exc:
                        entry.update(status="ambiguous" if exc.ambiguous else "failed", http_status=exc.status_code,
                                     error=str(exc), next_action="Inspect dataset item/status before retrying; this job never automatically replays an uncertain write.")
                    self.checkpoint()
                # Discover only this newly-created job dataset; never read other content.
                matches = [d for d in client.datasets() if d.get("name") == batch["dataset_name"]]
                if len(matches) == 1:
                    dataset["id"] = str(matches[0]["id"])
                    client.allowed_datasets.add(dataset["id"])
                    entry["dataset_id"] = dataset["id"]
                    self.checkpoint()
                if entry["status"] == "failed":
                    return {"state": "blocked", "reason": entry["error"], "dataset": batch["dataset_name"]}
            deadline = time.monotonic() + 90
            while True:
                complete = True
                for dataset in self.manifest["datasets"].values():
                    if not dataset.get("id"):
                        complete = False
                        continue
                    status = client.processing_status(dataset["id"])
                    dataset.update(processing=status, checked_at=stamp())
                    dataset["status"] = "complete" if status.get("total", 0) > 0 and status.get("pending") == 0 else "pending"
                    complete &= dataset["status"] == "complete"
                    for entry in ledger.values():
                        if entry.get("dataset_id") == dataset["id"]:
                            items = [i for i in status.get("items", []) if i.get("name") in
                                     {entry.get("filename"), Path(entry.get("filename", "")).stem}]
                            if len(items) == 1:
                                entry.update(data_id=items[0]["id"], status="complete" if items[0].get("completed") else "processing")
                self.checkpoint()
                if complete or time.monotonic() >= deadline:
                    break
                print(json.dumps({"stage": "ingest-cognee", "progress": "waiting_for_graph_indexing"}), flush=True)
                time.sleep(5)
            if not complete:
                return {"state": "pending", "reason": "Cognee accepted data; graph indexing is not complete. Resume ingest-cognee to inspect existing records."}
            for persona in self.load("personas.json"):
                dataset = self.manifest["datasets"][persona["id"]]
                for record in persona["session_entries"]:
                    key = content_hash([record["id"], content_hash(record), SCHEMA])
                    if key in ledger:
                        continue
                    entry = {"source_id": record["id"], "content_hash": content_hash(record), "schema_version": SCHEMA,
                             "dataset_name": dataset["name"], "session_id": record["session_id"], "scope": "session_only", "status": "inflight"}
                    ledger[key] = entry
                    self.checkpoint()
                    try:
                        response = client.remember_entry(dataset["name"], record["session_id"], record["text"], metadata=record,
                                                         question="Which temporary exception applies in this synthetic session?")
                        entry.update(status="complete", response=response, completed_at=stamp())
                    except CogneeError as exc:
                        entry.update(status="ambiguous" if exc.ambiguous else "failed", error=str(exc), http_status=exc.status_code)
                    self.checkpoint()
            unresolved = [e for e in ledger.values() if e["status"] not in {"accepted", "complete", "processing"}]
            return {"state": "pending" if unresolved else "complete", "datasets": len(self.manifest["datasets"]),
                    "durable_batches": len(batches), "session_entries": sum(e.get("scope") == "session_only" for e in ledger.values()),
                    "unresolved_writes": len(unresolved)}

    def verify(self):
        from app.preparation.verification import verify_prepared
        self.validated_documents()
        if self.dry_run:
            return {"state": "planned", "remote_mutations": 0}
        with self.cognee_client() as client:
            result = verify_prepared(client, self.manifest, self.load("normalized.json")["products"], self.load("personas.json"), self.output)
        if result.get("state") == "complete" and self.manifest["accepted_records"] == 6:
            self.manifest["smoke_verified"] = True
        return result

    def export_graph(self):
        from app.preparation.verification import export_prepared_graphs
        if self.dry_run:
            return {"state": "planned", "remote_mutations": 0}
        with self.cognee_client() as client:
            return export_prepared_graphs(client, self.manifest, self.load("personas.json"), self.output)
