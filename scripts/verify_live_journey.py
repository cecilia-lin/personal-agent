"""Exercise the running isolated API; save live evidence separately from pytest."""
import argparse
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    if args.base_url not in {"http://127.0.0.1:8011", "http://127.0.0.1:8012"}:
        raise ValueError("Use only the isolated acceptance server, not the active household")
    results = {"mode": "controlled_missing_key" if args.unavailable else "live_senso", "cases": {}}
    path = ROOT / ".local" / ("live-unavailable-acceptance.json" if args.unavailable else "live-journey-acceptance.json")
    def save():
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    with httpx.Client(base_url=args.base_url, timeout=240) as client:
        def request(method, route, body=None, expected=200):
            response = client.request(method, "/api" + route, json=body) if body is not None else client.request(method, "/api" + route)
            if response.status_code != expected:
                results["failure"] = {"route": route, "status": response.status_code, "response": response.json()}
                save()
                raise RuntimeError("Acceptance request returned unexpected status; inspect the local result")
            return response.json()
        def task():
            created = request("POST", "/tasks", {"goal": "Find a repairable desk light.", "requirement": "repairability"}, 201)
            return request("POST", "/tasks/" + created["id"] + "/run")
        def prepare(current):
            return request("POST", f"/tasks/{current['id']}/proposals", {"product_id": "arc-light"}, 201)
        def approve(proposal, expected=200):
            return request("POST", f"/proposals/{proposal['id']}/decision", {"decision": "approve", "terms_digest": proposal["terms_digest"]}, expected)
        before = request("GET", "/dashboard")
        request("PATCH", "/demo/budget", {"spendable_minor": 200000, "protected_minor": 50000, "spending_cap_minor": 50000})
        current = task()
        results["initial_task"] = current
        save()
        candidates = current["checkpoint"]["candidates"]
        arc = next(c for c in candidates if c["id"] == "arc-light")
        if args.unavailable:
            assert all(not c["proposal_allowed"] for c in candidates)
            assert all(c["verification"]["state"] in {"error", "not_verifiable", "pending"} for c in candidates)
            rejection = request("POST", f"/tasks/{current['id']}/proposals", {"product_id": "arc-light"}, 409)
            results["cases"]["C"] = {"passed": True, "kind": "controlled_missing_key_no_fixture_fallback", "rejection": rejection,
                                       "action_count": len(request("GET", "/dashboard")["actions"])}
            save()
            print(json.dumps({"mode": results["mode"], "passed": ["C"]}))
            return
        assert arc["verification"]["state"] == "supported" and arc["proposal_allowed"]
        fold = next(c for c in candidates if c["id"] == "fold-light")
        allowance = request("GET", "/dashboard")["budget"]["available_minor"]
        assert fold["repairable"] and fold["stock"] > 0 and fold["quote"]["complete"] and fold["total_minor"] <= allowance
        assert fold["verification"]["state"] == "conflict" and not fold["proposal_allowed"]
        rejection = request("POST", f"/tasks/{current['id']}/proposals", {"product_id": "fold-light"}, 409)
        results["cases"]["B"] = {"passed": True, "locally_affordable_and_repairable": True, "rejection": rejection, "verification": fold["verification"]}
        proposal = prepare(current)
        approved = approve(proposal)
        action = request("POST", f"/proposals/{proposal['id']}/execute")
        again = request("POST", f"/proposals/{proposal['id']}/execute")
        assert action["id"] == again["id"]
        results["cases"]["A"] = {"passed": True, "task_id": current["id"], "proposal": proposal, "approved": approved, "action": action}
        save()
        reserved = request("GET", "/dashboard")["budget"]
        request("POST", f"/actions/{action['id']}/remove")
        released = request("GET", "/dashboard")["budget"]
        request("POST", f"/actions/{action['id']}/remove")
        repeated = request("GET", "/dashboard")["budget"]
        assert released == repeated
        assert reserved["reservations_minor"] - released["reservations_minor"] == action["total_minor"]
        results["cases"]["E"] = {"passed": True, "reserved": reserved, "released": released, "repeated": repeated}
        next_task = task()
        stale = prepare(next_task)
        request("PATCH", "/demo/products/arc-light", {"price_minor": stale["terms"]["unit_price_minor"] + 100, "stock": 8})
        blocked = approve(stale, 409)
        request("POST", f"/proposals/{stale['id']}/execute", expected=409)
        results["cases"]["D"] = {"passed": True, "kind": "actual_product_quote_version_change", "rejection": blocked, "proposal_id": stale["id"]}
        # Restore only this isolated demo's original fixture price for visual QA.
        request("PATCH", "/demo/products/arc-light", {"price_minor": stale["terms"]["unit_price_minor"], "stock": 8})
        results["initial_action_count"] = len(before["actions"])
        results["final_action_count"] = len(request("GET", "/dashboard")["actions"])
        save()
        print(json.dumps({"mode": results["mode"], "passed": sorted(results["cases"])}))


if __name__ == "__main__":
    main()
