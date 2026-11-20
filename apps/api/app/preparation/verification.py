"""Evidence-based checks of prepared memory; never substitutes an illustrative graph."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from uuid import uuid4


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _rows(raw):
    return raw if isinstance(raw, list) else []


def _graph_parts(raw):
    if not isinstance(raw, dict):
        return [], []
    nodes, edges = raw.get("nodes", []), raw.get("links", raw.get("edges", []))
    return ([x for x in nodes if isinstance(x, dict)] if isinstance(nodes, list) else [],
            [x for x in edges if isinstance(x, dict)] if isinstance(edges, list) else [])


def _endpoint(value):
    return str(value.get("id", "")) if isinstance(value, dict) else str(value or "")


def _graph_report(raw):
    nodes, edges = _graph_parts(raw)
    ids = {str(node["id"]) for node in nodes if node.get("id")}
    connected = set()
    valid_edges = []
    for edge in edges:
        endpoints = {_endpoint(edge.get("source")), _endpoint(edge.get("target"))}
        if endpoints <= ids:
            valid_edges.append(edge)
            connected.update(endpoints)
    return {"node_count": len(nodes), "edge_count": len(edges), "connected_edge_count": len(valid_edges),
            "disconnected_node_count": len(ids - connected), "node_ids": sorted(ids),
            "edge_ids": sorted(str(edge["id"]) for edge in edges if edge.get("id")),
            "state": "complete" if nodes and valid_edges and len(nodes) <= 100 else "pending"}


def _render_graph_table(path, raw, label):
    nodes, edges = _graph_parts(raw)
    esc = lambda value: html.escape(str(value), quote=True)
    node_rows = "".join(f"<tr><td>{esc(n.get('id',''))}</td><td>{esc(n.get('name',n.get('label','')))}</td><td>{esc(n.get('type',''))}</td></tr>" for n in nodes)
    edge_rows = "".join(f"<tr><td>{esc(_endpoint(e.get('source')))}</td><td>{esc(e.get('relation',e.get('label','')))}</td><td>{esc(_endpoint(e.get('target')))}</td></tr>" for e in edges)
    Path(path).write_text("<!doctype html><meta charset='utf-8'><title>Actual Cognee graph export</title>"
                         "<style>body{font:15px system-ui;margin:2rem}table{border-collapse:collapse;width:100%;margin-bottom:2rem}td,th{border:1px solid #ddd;padding:.5rem;text-align:left;overflow-wrap:anywhere}</style>"
                         f"<h1>{esc(label)}</h1><p>Actual authenticated Cognee bounded subgraph. {len(nodes)} nodes, {len(edges)} edges. This table does not invent relationships.</p>"
                         "<h2>Nodes</h2><table><tr><th>ID</th><th>Name</th><th>Type</th></tr>" + node_rows + "</table>"
                         "<h2>Edges</h2><table><tr><th>Source</th><th>Relation</th><th>Target</th></tr>" + edge_rows + "</table>", encoding="utf-8")


def export_prepared_graphs(client, manifest, personas, output):
    """Export only this job's catalog and first synthetic persona, at 100 nodes each."""
    output = Path(output)
    targets = [("catalog", "catalog")]
    if personas:
        targets.append((personas[0]["id"], "persona-a"))
    reports = {}
    for key, filename in targets:
        dataset = manifest.get("datasets", {}).get(key, {})
        if not dataset.get("id"):
            reports[key] = {"state": "pending", "reason": "Dataset ID is not available"}
            continue
        try:
            raw = client.export_graph(dataset["id"], max_nodes=100)
            raw_path = output / "graphs" / (filename + ".json")
            _save(raw_path, raw)
            report = _graph_report(raw)
            report.update(dataset_id=dataset["id"], raw_path=str(raw_path),
                          html_path=str(raw_path.with_suffix(".html")))
            _render_graph_table(raw_path.with_suffix(".html"), raw, dataset.get("name", key))
            reports[key] = report
        except Exception as exc:
            reports[key] = {"state": "pending", "error_class": type(exc).__name__,
                            "reason": "Actual graph export is unavailable; no graph is asserted"}
    result = {"state": "complete" if len(reports) == 2 and all(x["state"] == "complete" for x in reports.values()) else "pending",
              "graphs": reports, "bounded_nodes_per_graph": 100}
    _save(output / "graph-report.json", result)
    return result


def _support(raw, graph_ids):
    rows = [row for row in _rows(raw) if isinstance(row, dict) and row.get("source") == "graph"]
    reference_ids = set()

    def identifiers(value):
        if isinstance(value, dict):
            for key, item in value.items():
                # The live tenant returns metadata.evidence[].artifact_id, with
                # source/target node IDs for graph edges. Other supported forms
                # are explicit used_graph_element_ids nodes/edges lists.
                if key in {"artifact_id", "node_id", "edge_id", "data_id", "chunk_id", "source_node_id",
                           "target_node_id", "node_ids", "edge_ids", "data_ids", "chunk_ids", "nodes", "edges"}:
                    for candidate in _strings(item):
                        if len(candidate) <= 200 and not any(c.isspace() for c in candidate):
                            yield candidate
                elif isinstance(item, (dict, list)):
                    yield from identifiers(item)
        elif isinstance(value, list):
            for item in value:
                yield from identifiers(item)

    for row in rows:
        for key in ("metadata", "raw", "used_graph_element_ids", "references"):
            reference_ids.update(identifiers(row.get(key, {})))
    # Only externally returned IDs found in actual exported nodes/edges count.
    supporting = sorted(reference_ids & graph_ids)
    return {"graph_result_count": len(rows), "supporting_graph_ids": supporting,
            "returned_reference_ids": sorted(reference_ids),
            "source_tags": sorted({str(row.get("source")) for row in _rows(raw) if isinstance(row, dict)})}


def _normalized(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _evidence_text(raw):
    """Exclude the echoed question/system prompt from context-only fact checks."""
    passages = []
    for row in _rows(raw):
        if not isinstance(row, dict):
            continue
        if row.get("source") == "session":
            passages.append(str(row.get("answer", "")))
        elif row.get("source") == "graph":
            text = str(row.get("text", ""))
            blocks = re.findall(r"__node_content_start__\s*(.*?)\s*__node_content_end__", text, re.S)
            # The observed tenant provides these boundaries. Plain answers are
            # supported for mocks/other retrieval kinds, but a context envelope
            # without recognizable evidence boundaries cannot verify facts.
            passages.extend(blocks if blocks else ([] if "The question is:" in text else [text]))
    return _normalized(" ".join(passages))


def verify_prepared(client, manifest, products, personas, output):
    """Six recalls, plus at most three bounded catalog coverage follow-ups.

    Context-only graph retrieval avoids generating an answer or adding another QA
    entry. Queries never restate the confirmed preference. Every passing graph
    check needs a returned supporting ID present in an actual exported graph.
    """
    output = Path(output)
    graph_report = export_prepared_graphs(client, manifest, personas, output)
    if not products or not personas:
        result = {"state": "pending", "reason": "Prepared products and personas are required", "checks": []}
        _save(output / "verification.json", result)
        return result
    persona = personas[0]
    catalog_ds = manifest.get("datasets", {}).get("catalog", {}).get("id")
    persona_ds = manifest.get("datasets", {}).get(persona["id"], {}).get("id")
    if not catalog_ds or not persona_ds:
        result = {"state": "pending", "reason": "Prepared dataset IDs are missing", "checks": []}
        _save(output / "verification.json", result)
        return result
    graphs = graph_report["graphs"]
    catalog_ids = set(graphs.get("catalog", {}).get("node_ids", [])) | set(graphs.get("catalog", {}).get("edge_ids", []))
    persona_ids = set(graphs.get(persona["id"], {}).get("node_ids", [])) | set(graphs.get(persona["id"], {}).get("edge_ids", []))
    exported_nodes = []
    for report in graphs.values():
        if report.get("raw_path"):
            exported_nodes.extend(_graph_parts(json.loads(Path(report["raw_path"]).read_text(encoding="utf-8")))[0])
    completed_data_ids = {entry["data_id"] for entry in manifest.get("cognee_ledger", {}).values()
                          if entry.get("status") == "complete" and entry.get("data_id")}
    product = products[0]
    eligible = [p for p in products if (p.get("return_window_days") or 0) >= 30]
    current = next((r for r in persona["durable_records"] if r.get("type") == "confirmed_preference"), None)
    expected_requirement = (current or {}).get("requirement", {})
    # A new identifier is created on EVERY verification run; none of the older
    # preference or exception texts is written or replayed into this session.
    fresh_session = persona.get("new_session_id", "intent-fresh") + ":" + uuid4().hex[:10]
    checks = []

    def recall_check(name, query, datasets, scope, expected, predicate, graph_ids, session_id=None):
        request = {"query": query, "datasets": datasets, "scope": scope, "session_id": session_id}
        if scope == "graph":
            request.update(search_type="GRAPH_COMPLETION", only_context=True, top_k=20)
        try:
            raw = client.recall(**request)
            _save(output / "recall" / (name + ".json"), {"request": request, "response": raw})
            supplemental_paths = []
            if name == "01-return-policies" and isinstance(raw, list):
                observed = _evidence_text(raw)
                missing = [p for p in eligible if _normalized(p["product_id"]) not in observed
                           or _normalized(p["policies"]["return_policy"]) not in observed]
                # A bounded top-k query is not an exhaustive catalog scan. When
                # expansion spans several source batches, retrieve missing IDs
                # in small groups, without feeding their expected policy values.
                for index in range(0, min(len(missing), 12), 4):
                    supplemental = dict(request, search_type="CHUNKS_LEXICAL",
                                        query=" ".join(p["product_id"] for p in missing[index:index + 4]) + " return_policy")
                    extra = client.recall(**supplemental)
                    extra_path = output / "recall" / f"{name}-part-{index // 4 + 1}.json"
                    _save(extra_path, {"request": supplemental, "response": extra})
                    supplemental_paths.append(str(extra_path))
                    if isinstance(extra, list):
                        raw = raw + extra
            support = _support(raw, graph_ids)
            # Examine returned body fields only; don't include request/expected
            # fixtures in the matching text. Neither preference nor shipping
            # answer was supplied in the corresponding retrieval query.
            linked_chunks, backed_passages = [], []
            for row in _rows(raw):
                if not isinstance(row, dict):
                    continue
                if scope != "graph" or _support([row], graph_ids)["supporting_graph_ids"]:
                    backed_passages.append(_evidence_text([row]))
                elif row.get("source") == "graph" and row.get("kind") == "chunk":
                    # CHUNKS_LEXICAL on this tenant omits citation metadata.
                    # Recover provenance only by exact exported chunk content,
                    # graph node ID, and a completed document in our own ledger.
                    returned = _evidence_text([row])
                    for node in exported_nodes:
                        chunk = _normalized(node.get("text", ""))
                        if (node.get("id") in graph_ids and node.get("document_id") in completed_data_ids
                                and len(chunk) >= 100 and chunk in returned):
                            backed_passages.append(chunk)
                            linked_chunks.append({"graph_node_id": node["id"], "document_id": node["document_id"],
                                                  "link_method": "exact_exported_chunk_text_match"})
            support["export_linked_chunks"] = list({x["graph_node_id"]: x for x in linked_chunks}.values())
            support["supporting_graph_ids"] = sorted(set(support["supporting_graph_ids"]) | {x["graph_node_id"] for x in linked_chunks})
            text = _normalized(" ".join(backed_passages))
            factual = bool(predicate(text, raw))
            provenance = bool(support["graph_result_count"] and support["supporting_graph_ids"]) if scope == "graph" else any(
                isinstance(row, dict) and row.get("source") == "session" and row.get("qa_id") for row in _rows(raw))
            result = {"name": name, "state": "passed" if factual and provenance else "pending",
                      "expected": expected, "fact_matched": factual, "provenance_verified": provenance,
                      **support, "raw_path": str(output / "recall" / (name + ".json")),
                      "supplemental_raw_paths": supplemental_paths}
        except Exception as exc:
            result = {"name": name, "state": "pending", "error_class": type(exc).__name__,
                      "reason": "No verified recall response was available"}
        checks.append(result)

    recall_check("01-return-policies", "Which selected products have an explicitly stated return window of at least 30 days? Include each stable product ID and the exact recorded policy statement.",
                 [catalog_ds], "graph", [{"product_id": p["product_id"], "policy": p["policies"]["return_policy"]} for p in eligible],
                 lambda text, raw: bool(eligible) and all(_normalized(p["product_id"]) in text and _normalized(p["policies"]["return_policy"]) in text for p in eligible), catalog_ids)
    shipping = product["policies"].get("shipping")
    recall_check("02-shipping", f"What shipping statement is recorded for {product['product_id']}? Return the exact source wording.",
                 [catalog_ds], "graph", shipping,
                 lambda text, raw: bool(shipping) and _normalized(shipping) in text, catalog_ids)
    warranty = product["policies"].get("warranty")
    recall_check("03-warranty-source", f"Which source supports the warranty for {product['product_id']}? Include the exact recorded warranty statement and source version.",
                 [catalog_ds], "graph", {"warranty": warranty, "source_version": product["source_version"]},
                 lambda text, raw: bool(warranty) and _normalized(warranty) in text and _normalized(product["source_version"]) in text, catalog_ids)
    recall_check("04-fresh-durable-requirement", f"What currently confirmed shopping requirement did synthetic user {persona['id']} state in an earlier session? Retrieve its confirmation and correction history.",
                 [persona_ds], "graph", expected_requirement,
                 lambda text, raw: bool(current) and "return" in text and bool(re.search(r"\b" + str(expected_requirement.get("value")) + r"[ -]*days?\b", text)) and "confirmed" in text,
                 persona_ids, session_id=fresh_session)
    exception = persona["session_entries"][0]
    recall_check("05-current-session-exception", "Which temporary exception applies only to this session?", [persona_ds], "session",
                 {"scope": "session_only", "entry_id": exception["id"]},
                 lambda text, raw: "unknown return windows" in text and ("session only" in text or "session-only" in text),
                 set(), session_id=persona["session_id"])
    # This read must find no earlier QA in the genuinely new session. Source=graph
    # here would indicate routing/scoping uncertainty, not an empty session pass.
    try:
        query = {"query": "Which temporary exception applies to this session?", "datasets": [persona_ds],
                 "session_id": fresh_session, "scope": "session"}
        raw = client.recall(**query)
        _save(output / "recall" / "06-fresh-session-isolation.json", {"request": query, "response": raw})
        empty = isinstance(raw, list) and len(raw) == 0
        checks.append({"name": "06-fresh-session-isolation", "state": "passed" if empty else "pending",
                       "empty_session_confirmed": empty, "session_id": fresh_session})
    except Exception as exc:
        checks.append({"name": "06-fresh-session-isolation", "state": "pending", "error_class": type(exc).__name__})
    passed = sum(check["state"] == "passed" for check in checks)
    result = {"state": "complete" if passed == 6 and graph_report["state"] == "complete" else "pending",
              "verified_at": datetime.now(timezone.utc).isoformat(), "passed": passed, "total": 6,
              "five_fact_examples_passed": all(check["state"] == "passed" for check in checks[:5]),
              "fresh_session_id": fresh_session, "checks": checks, "graph_report": graph_report,
              "specialist_model_calls": 0, "recall_mode": "context_only_graph_and_typed_session",
              "application_decision_changed": False,
              "application_bridge": "pending until memory proof and existing decision-rule bridge are verified"}
    _save(output / "verification.json", result)
    return result
