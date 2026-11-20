"""Verify the read-only research bridge against the isolated running app."""
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    response = httpx.post("http://127.0.0.1:8011/api/research-memory/recall", json={}, timeout=120)
    response.raise_for_status()
    result = response.json()
    output = ROOT / ".local/cognee-job-smoke/app-bridge.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"state": result["state"], "reason": result["reason"],
                      "candidate_states": [c["requirement_state"] for c in result["candidates"]],
                      "proposal_allowed": result["proposal_allowed"]}))
    return 0 if result["state"] == "ready" and {c["requirement_state"] for c in result["candidates"]} == {"supported", "contradicted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
