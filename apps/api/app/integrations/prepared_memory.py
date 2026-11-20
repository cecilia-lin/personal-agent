"""Read-only PreferenceMemory adapter for one verified synthetic preparation job."""
from __future__ import annotations

import json
from pathlib import Path
import re
from uuid import uuid4

from app.integrations.cognee import CogneeClient
from app.preparation.job import content_hash
from app.preparation.verification import _graph_report, _strings


class PreparedMemoryError(RuntimeError):
    def __init__(self, message: str, *, state="blocked"):
        super().__init__(message)
        self.state = state


def _read(path: Path):
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise PreparedMemoryError("The bounded preparation artifacts are not available.", state="pending")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise PreparedMemoryError("A preparation artifact is invalid; rerun validation.") from None


def _has_confirmed_requirement(value):
    text = " ".join(_strings(value)).casefold()
    return bool("return" in text and "confirmed" in text and re.search(r"\b30[ -]*days?\b", text))


class PreparedPreferenceMemory:
    """Implements PreferenceMemory.recall without accepting active household IDs.

    The output directory is trusted application configuration, never a request
    parameter. All remote reads are restricted to the selected synthetic persona.
    """

    def __init__(self, output, persona_key="A", *, client=None):
        if persona_key not in {"A", "B", "C"}:
            raise PreparedMemoryError("Only a prepared synthetic persona may be recalled.")
        self.output = Path(output).resolve()
        self.manifest = _read(self.output / "manifest.json")
        verification = self.manifest.get("stages", {}).get("verify", {})
        if (self.manifest.get("smoke_verified") is not True or verification.get("state") != "complete"
                or verification.get("dry_run") is not False
                or verification.get("result", {}).get("state") != "complete"):
            raise PreparedMemoryError("Live preparation and graph verification must finish before this demo can recall memory.", state="pending")
        self.artifacts = {}
        for name in ("normalized.json", "documents.json", "research-findings.json", "personas.json"):
            value = _read(self.output / name)
            if self.manifest.get("validated_artifacts", {}).get(name) != content_hash(value):
                raise PreparedMemoryError("Prepared artifacts changed after validation; recall is blocked.")
            self.artifacts[name] = value
        owner = self.manifest.get("config", {}).get("synthetic_owner", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", owner) or owner == "demo-user":
            raise PreparedMemoryError("The prepared synthetic owner is invalid.")
        self.user_id = owner + ":persona:" + persona_key
        matches = [p for p in self.artifacts["personas.json"] if p.get("id") == self.user_id]
        if len(matches) != 1 or not matches[0].get("synthetic_demo") or matches[0].get("owner") != self.user_id:
            raise PreparedMemoryError("The requested synthetic persona is not validated.")
        self.persona = matches[0]
        self.dataset = self.manifest.get("datasets", {}).get(self.user_id, {})
        if not self.dataset.get("id") or self.dataset.get("status") != "complete":
            raise PreparedMemoryError("The synthetic persona graph is not indexed yet.", state="pending")
        self.data_ids = sorted({e["data_id"] for e in self.manifest.get("cognee_ledger", {}).values()
                                if e.get("dataset_id") == self.dataset["id"] and e.get("source_id") == self.user_id
                                and e.get("status") == "complete" and e.get("data_id")})
        if not self.data_ids:
            raise PreparedMemoryError("No completed persona ingestion is present in the source ledger.", state="pending")
        current = [r for r in self.persona.get("durable_records", [])
                   if r.get("type") == "confirmed_preference" and r.get("status") == "confirmed"
                   and r.get("synthetic_demo") is True and r.get("owner") == self.user_id
                   and r.get("scope") != "session_only"]
        if len(current) != 1 or current[0].get("requirement") != {"kind": "minimum_return_window_days", "value": 30}:
            raise PreparedMemoryError("The prepared current requirement is unsupported or ambiguous.")
        self.current = current[0]
        self.client = client
        self.session_id = None

    def remember(self, user_id: str, preference: dict) -> None:
        raise PreparedMemoryError("This read-only demo does not write preferences; use the isolated preparation job.")

    def recall(self, user_id: str, query: str) -> list[dict]:
        if user_id != self.user_id:
            raise PreparedMemoryError("Recall is restricted to the selected synthetic persona.")
        if not isinstance(query, str) or len(query) > 2000:
            raise PreparedMemoryError("The recall query is invalid.")
        self.session_id = self.manifest["job_id"] + ":app-fresh:" + uuid4().hex
        # Do not replay the required value, prior preference, or old exception.
        question = f"What currently confirmed shopping requirement did synthetic user {self.user_id} state in an earlier session? Retrieve its confirmation and correction history."
        client = self.client or CogneeClient.from_env(allowed_datasets={self.dataset["id"]})
        try:
            raw_graph = client.export_graph(self.dataset["id"], max_nodes=100)
            graph = _graph_report(raw_graph)
            if graph["state"] != "complete":
                raise PreparedMemoryError("The actual persona graph cannot be verified yet.", state="pending")
            raw = client.recall(question, datasets=[self.dataset["id"]], session_id=self.session_id,
                                scope="graph", search_type="GRAPH_COMPLETION", only_context=True, top_k=20)
            if not isinstance(raw, list):
                raise PreparedMemoryError("The memory service returned an unsupported recall shape.", state="pending")
            scoped = [row for row in raw if isinstance(row, dict) and row.get("source") == "graph"
                      and row.get("dataset_id") in {None, self.dataset["id"]}
                      and row.get("dataset_name") in {None, self.dataset.get("name")}]
            qualifying_nodes = {str(node["id"]) for node in raw_graph.get("nodes", [])
                                if isinstance(node, dict) and node.get("id")
                                and _has_confirmed_requirement({key: node.get(key) for key in ("name", "text", "description")})}
            # Validate factual text and references on the SAME result row.
            accepted = []
            for row in scoped:
                supports_value = _has_confirmed_requirement({key: row.get(key) for key in ("text", "structured")})
                evidence = row.get("metadata", {}).get("evidence", [])
                references = {item.get("artifact_id") for item in evidence if isinstance(item, dict)
                              and item.get("kind") == "graph_node" and item.get("dataset_id") == self.dataset["id"]}
                supported_ids = references & qualifying_nodes
                if supports_value and supported_ids:
                    accepted.append((row, supported_ids))
            if not accepted:
                raise PreparedMemoryError("Live graph recall did not establish the confirmed requirement with matching source IDs.", state="pending")
            source_ids = sorted({ref for _, evidence in accepted for ref in evidence})
            return [{"id": self.current["id"], "text": self.current["text"], **self.current["requirement"],
                     "source": "cognee_graph", "source_ids": source_ids, "data_ids": self.data_ids,
                     "dataset_id": self.dataset["id"], "persona_id": self.user_id,
                     "session_id": self.session_id, "synthetic_demo": True,
                     "retrieved_text": accepted[0][0].get("text", "")[:12000]}]
        except PreparedMemoryError:
            raise
        except Exception:
            raise PreparedMemoryError("Live memory retrieval is unavailable; no remembered requirement is asserted.", state="pending") from None
        finally:
            if self.client is None:
                client.close()
