"""Exercise the running local API. Creates synthetic data; removes its own cart."""
import json
import httpx

with httpx.Client(base_url="http://127.0.0.1:8000/api", timeout=30) as client:
    def call(method, route, body=None):
        response = client.request(method, route, json=body)
        response.raise_for_status()
        return response.json()
    call("GET", "/health")
    before = call("GET", "/dashboard")
    imported = call("POST", "/imports/bill", {"text": before["sample_bill"]})
    bill = call("POST", f"/imports/bill/{imported['id']}/confirm", imported["fields"])
    repeated = call("POST", f"/imports/bill/{imported['id']}/confirm", imported["fields"])
    assert repeated["duplicate"]
    task = call("POST", "/tasks", {"goal": "Smoke check: a repairable desk light with a valid email promotion"})
    task = call("POST", f"/tasks/{task['id']}/run")
    candidate = next(c for c in task["checkpoint"]["candidates"] if c["eligible"])
    proposal = call("POST", f"/tasks/{task['id']}/proposals", {"product_id": candidate["id"]})
    decision = {"decision": "approve", "terms_digest": proposal["terms_digest"]}
    call("POST", f"/proposals/{proposal['id']}/decision", decision)
    action = call("POST", f"/proposals/{proposal['id']}/execute")
    assert call("POST", f"/proposals/{proposal['id']}/execute")["id"] == action["id"]
    call("POST", f"/proposals/{proposal['id']}/decision", decision)
    assert action["cart"]["code_validation"] == "confirmed_by_demo_merchant"
    call("POST", f"/actions/{action['id']}/remove")
    call("POST", f"/actions/{action['id']}/remove")
    scan = call("POST", "/background/scan")
    next_count = len(call("GET", "/dashboard")["next_actions"])
    call("POST", "/background/scan")
    assert len(call("GET", "/dashboard")["next_actions"]) == next_count
    print(json.dumps({"result": "passed", "task_id": task["id"], "bill_id": bill["bill"]["id"],
                      "total_minor": action["total_minor"], "promotion": action["cart"]["applied_code"],
                      "duplicate_execution": "same action", "removal": "released once", "scan_run_id": scan["run_id"]}, indent=2))
