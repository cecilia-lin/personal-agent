"""Bounded Cognee tenant REST adapter for the isolated preparation job.

Contracts were checked against the configured tenant's OpenAPI on 2026-11-20.
Results remain unmodified so callers can retain external IDs and provenance.
This client does not interpret acceptance as processing or retrieval success.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from dotenv import dotenv_values


class CogneeError(RuntimeError):
    """Safe diagnostic; ambiguous writes must be reconciled before retrying."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 ambiguous: bool = False, response: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.ambiguous = ambiguous
        self.response = response


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("An explicit dataset UUID is required") from None


def _name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {"main_dataset", "default_dataset"}:
        raise ValueError("An explicit job-owned dataset is required")
    if len(value) > 200 or any(char in value for char in "\r\n/\\"):
        raise ValueError("Invalid dataset name")
    return value


class CogneeClient:
    def __init__(self, api_key: str, base_url: str, *, transport=None,
                 allowed_datasets: Iterable[str] | None = None,
                 timeout: float = 25, max_response_bytes: int = 4_000_000,
                 read_retries: int = 1):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".cognee.ai")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or parsed.port not in {None, 443}):
            raise ValueError("Use the configured HTTPS Cognee tenant origin")
        if not api_key:
            raise ValueError("COGNEE_API_KEY is required")
        if not 0 < timeout <= 30 or not 1 <= max_response_bytes <= 10_000_000 or read_retries not in {0, 1, 2}:
            raise ValueError("Cognee request bounds are invalid")
        self.allowed_datasets = set(allowed_datasets) if allowed_datasets is not None else None
        self.max_response_bytes = max_response_bytes
        self.read_retries = read_retries
        self.http = httpx.Client(base_url=base_url.rstrip("/"),
                                 headers={"X-Api-Key": api_key, "Accept": "application/json"},
                                 timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
                                 follow_redirects=False, transport=transport)

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, **kwargs) -> "CogneeClient":
        root = Path(__file__).resolve().parents[4]
        values = {**dotenv_values(env_file or root / ".env"), **os.environ}
        return cls(api_key=values.get("COGNEE_API_KEY", ""),
                   base_url=values.get("COGNEE_BASE_URL", ""), **kwargs)

    def _authorize(self, dataset: str) -> None:
        if self.allowed_datasets is not None and dataset not in self.allowed_datasets:
            raise ValueError("Dataset is outside this client's explicit authorized scope")

    def _request(self, method: str, path: str, **kwargs) -> Any:
        # Even recall can write session/history: no POST is automatically repeated.
        attempts = 1 + (self.read_retries if method == "GET" else 0)
        for attempt in range(attempts):
            try:
                with self.http.stream(method, path, **kwargs) as response:
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            raise CogneeError("Cognee response exceeded the configured byte limit",
                                              ambiguous=method != "GET")
                    try:
                        payload = json.loads(content)
                    except (ValueError, UnicodeDecodeError):
                        payload = None
                    if response.status_code in {429, 502, 503, 504} and attempt + 1 < attempts:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    if not 200 <= response.status_code < 300:
                        raise CogneeError(f"Cognee request failed (HTTP {response.status_code})",
                                          status_code=response.status_code,
                                          ambiguous=method != "GET" and response.status_code >= 500,
                                          response=payload)
                    if payload is None:
                        raise CogneeError("Cognee did not return a JSON response",
                                          ambiguous=method != "GET")
                    return payload
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise CogneeError(f"Cognee request failed ({type(exc).__name__})",
                                  ambiguous=method != "GET") from None
        raise AssertionError("Unreachable request retry state")

    def openapi(self) -> dict:
        return self._request("GET", "/openapi.json")

    def datasets(self) -> list[dict]:
        """Dataset metadata only; does not retrieve existing dataset contents."""
        result = self._request("GET", "/api/v1/datasets/")
        if not isinstance(result, list):
            raise CogneeError("Cognee dataset metadata has an unexpected shape")
        return result

    def remember(self, text: str, dataset_name: str, *, filename: str = "memory.txt",
                 metadata: dict | None = None) -> Any:
        """Durable add+cognify, without the session cache or automatic improve."""
        _name(dataset_name)
        self._authorize(dataset_name)
        if not text.strip() or len(text.encode("utf-8")) > 500_000:
            raise ValueError("Memory documents must contain 1 to 500000 UTF-8 bytes")
        if not filename or Path(filename).name != filename or any(c in filename for c in "\r\n/\\"):
            raise ValueError("Use a stable plain filename")
        form = {"datasetName": dataset_name, "run_in_background": "true",
                "self_improvement": "false", "chunks_per_batch": "2"}
        if metadata is not None:
            form["external_metadata"] = json.dumps([metadata], ensure_ascii=False)
        return self._request("POST", "/api/v1/remember", data=form,
                             files={"data": (filename, text.encode("utf-8"), "text/plain")})

    def remember_entry(self, dataset_name: str, session_id: str, text: str, *,
                       metadata: dict | None = None,
                       question: str = "What applies to this synthetic demonstration session?") -> Any:
        """Typed session QA. This endpoint does not promote entries into the graph."""
        _name(dataset_name)
        self._authorize(dataset_name)
        if not session_id or not text.strip() or not question.strip() or len(text) > 50_000:
            raise ValueError("An explicit session and bounded nonempty QA entry are required")
        entry = {"type": "qa", "question": question, "answer": text}
        if metadata is not None:
            entry["context"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        return self._request("POST", "/api/v1/remember/entry", json={
            "dataset_name": dataset_name, "session_id": session_id,
            "entry": entry, "self_improvement": False,
        })

    def status(self, dataset_id: str) -> Any:
        _uuid(dataset_id)
        self._authorize(dataset_id)
        return self._request("GET", "/api/v1/datasets/status", params={"dataset": dataset_id})

    def processing_status(self, dataset_id: str, *, pipeline: str = "cognify_pipeline") -> Any:
        _uuid(dataset_id)
        self._authorize(dataset_id)
        if pipeline not in {"cognify_pipeline", "add_pipeline", "indexing_pipeline"}:
            raise ValueError("Unsupported preparation pipeline")
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/processing-status",
                             params={"pipeline": pipeline})

    def recall(self, query: str, *, datasets: list[str], session_id: str | None = None,
               scope: str = "graph", search_type: str | None = None,
               only_context: bool = False, top_k: int = 10) -> Any:
        """Explicit source and dataset scope, preserving source tags and provenance."""
        if not datasets or len(datasets) > 4 or not query.strip() or len(query) > 10_000:
            raise ValueError("Recall needs a bounded query and explicit authorized datasets")
        if scope not in {"graph", "session", "session_first"} or not 1 <= top_k <= 20:
            raise ValueError("Unsupported or unbounded recall scope")
        if scope != "graph" and (not session_id or search_type is not None):
            raise ValueError("Session recall needs a session and no pinned graph search type")
        kinds = []
        for dataset in datasets:
            self._authorize(dataset)
            try:
                _uuid(dataset)
                kinds.append("id")
            except ValueError:
                _name(dataset)
                kinds.append("name")
        # datasetIds wins over datasets on the server: mixed lists could lose scope.
        if len(set(kinds)) != 1:
            raise ValueError("Use all dataset names or all dataset UUIDs, never a mixed list")
        payload = {"query": query, "scope": scope, "topK": top_k,
                   "onlyContext": only_context, "includeReferences": True, "stream": False,
                   "datasetIds" if kinds[0] == "id" else "datasets": datasets}
        if session_id:
            payload["sessionId"] = session_id
        if search_type is not None:
            if search_type not in {"HYBRID_COMPLETION", "GRAPH_COMPLETION", "CHUNKS", "CHUNKS_LEXICAL", "SUMMARIES"}:
                raise ValueError("Unsupported preparation search type")
            payload["searchType"] = search_type
        return self._request("POST", "/api/v1/recall", json=payload)

    def export_graph(self, dataset_id: str, *, max_nodes: int = 100,
                     seed_node_ids: list[str] | None = None) -> Any:
        _uuid(dataset_id)
        self._authorize(dataset_id)
        if not 1 <= max_nodes <= 100 or seed_node_ids is not None and len(seed_node_ids) > 10:
            raise ValueError("Graph exports are bounded to 100 nodes and 10 seeds")
        params = {"dataset_id": dataset_id, "full": "false", "max_nodes": max_nodes,
                  "stream": "false", "include_session_events": "false"}
        if seed_node_ids:
            params["seed_node_ids"] = seed_node_ids
        return self._request("GET", "/api/v1/visualize/json", params=params)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "CogneeClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
