"""Bounded live connectivity checks. Exports only synthetic verification metadata."""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
os.environ["INTEGRATIONS_ENABLED"] = "true"
from app.integrations.senso import evidence_provider
from app.integrations import statsig_client, amplitude_client
from sie_sdk import SIEClient
results = {"checked_at": datetime.now(timezone.utc).isoformat()}
senso = evidence_provider()
if hasattr(senso, "check_connection"):
    senso.check_connection()
    passages = senso.for_product({"id": "arc-light", "name": "Arc Light"}) if senso.connected else []
    results["Senso"] = {**senso.status(), "matching_passages": len(passages),
        "citations_have_versions": bool(passages) and all(p.get("version_id") for p in passages)}
    senso.close()
else:
    results["Senso"] = {"status": "not_configured"}
statsig_client.initialize()
results["Statsig"] = {**statsig_client.status(), "gate": statsig_client.choose_reranker("intent-verification")}
statsig_client.shutdown()
amplitude_client.initialize()
amplitude_client.track_metadata("intent-verification", {
    "id": "verification_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
    "kind": "integration_check", "timestamp": results["checked_at"],
    "task_id": "synthetic-verification-task", "session_id": "synthetic-verification-session",
    "run_id": "synthetic-verification-run", "provenance": "simulated", "latency_ms": None,
})
if amplitude_client.client:
    for future in amplitude_client.client.flush() or []:
        if future:
            try: future.result(timeout=20)
            except Exception: pass
results["Amplitude"] = amplitude_client.status()
amplitude_client.shutdown()
if os.getenv("SIE_API_KEY"):
    sie = SIEClient(api_key=os.environ["SIE_API_KEY"],
        base_url=os.getenv("SIE_BASE_URL", "https://api.superlinked.com"), timeout_s=15)
    try:
        models = sie.list_models()
        results["SIE"] = {"catalog_verified": True, "models": models}
        from app.integrations.sie import SIERanker
        ranker = SIERanker(client=sie)
        if any(m.get("name") == ranker.model and "score" in m.get("outputs", []) for m in models):
            candidates = [{"id":"arc-light","name":"Arc Light","description":"Repairable desk light with replaceable LED.", "eligible": True},
                          {"id":"fold-light","name":"Fold Light","description":"A repairable task lamp with folding arm.", "eligible": True}]
            results["SIE"]["scoring"] = ranker.score(candidates, "desk-light", True)
            results["SIE"]["score_verified"] = ranker.verified
        else:
            results["SIE"]["score_verified"] = False
            results["SIE"]["reason"] = "Configured ranking model is absent from the account catalog."
    except Exception as exc:
        results["SIE"] = {"catalog_verified": False, "error_class": type(exc).__name__}
    finally: sie.close()
else: results["SIE"] = {"status": "not_configured"}
results["Guild"] = {"configured": bool(os.getenv("GUILD_API_KEY")), "deployed": False}
results["SingleStore"] = {"configured": bool(os.getenv("SINGLESTORE_HOST")), "verified": False}
out = ROOT / ".local/sponsor-verification.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
summary = {**results, "SIE": {k:v for k,v in results.get("SIE",{}).items() if k!="models"}}
if "models" in results.get("SIE",{}):
    summary["SIE"]["model_count"] = len(results["SIE"]["models"])
print(json.dumps(summary,indent=2))
