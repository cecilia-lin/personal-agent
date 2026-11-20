"""Live SQL checks with synthetic records under one unique owner, cleaned up afterward.

Run after migration: .venv/Scripts/python.exe scripts/verify_singlestore.py
No sponsor telemetry, merchant requests, or existing user records are touched.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import traceback
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
os.environ["INTEGRATIONS_ENABLED"] = "false"

from app.config import DEMO_USER, Settings
from app.domain.models import BillConfirmation, CreateTask, Decision, PrepareProposal, Problem, SourceImport
from app.repositories.store import Store, TABLES
from app.services.agent import AgentService


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print("PASS: " + label, flush=True)


def main():
    settings = replace(Settings.from_env(), db_backend="singlestore", mode="demo")
    store = Store(settings)
    owner = "sql-verification-" + uuid4().hex
    service = AgentService(store, settings)
    checks = []
    try:
        check(store.diagnostic(), "TLS SQL connection")
        with TemporaryDirectory() as directory:
            local_settings = Settings(sqlite_path=Path(directory) / "seed.db")
            local = Store(local_settings)
            local.initialize()
            seed_service = AgentService(local, local_settings)
            seed_service.seed()
            with local.transaction(DEMO_USER) as source, store.transaction(owner, write=True) as target:
                for table in TABLES:
                    records = source.execute(f"SELECT id, version, payload FROM {table} WHERE user_id=?", (DEMO_USER,)).fetchall()
                    if records:
                        target.connection.cursor().executemany(
                            f"INSERT INTO {table} (user_id,id,version,payload) VALUES (%s,%s,%s,%s)",
                            [(owner, *record) for record in records],
                        )

        with store.transaction(owner + "-other") as unit:
            check(unit.get("accounts", "cash", False) is None, "owner isolation")
        with store.transaction(owner, write=True) as unit:
            text = "\u00e9" * 50000
            saved = unit.save("sources", "large-payload-probe", {"raw_text": text})
            check(saved["raw_text"] == text, "large Unicode document round trip")
        delivered = []
        try:
            with store.transaction(owner, write=True) as unit:
                unit.save("adjustments", "rollback-probe", {"amount_minor": 1})
                unit.after_commit.append(lambda: delivered.append(True))
                raise RuntimeError("intentional rollback")
        except RuntimeError:
            pass
        with store.transaction(owner) as unit:
            check(unit.get("adjustments", "rollback-probe", False) is None and not delivered,
                  "rollback and after-commit isolation")

        with store.transaction(owner, write=True) as unit:
            account = unit.get("accounts", "cash")
            unit.save("accounts", "cash", account, account["version"])
        try:
            with store.transaction(owner, write=True) as unit:
                unit.save("accounts", "cash", account, account["version"])
            raise AssertionError("stale update accepted")
        except Problem:
            check(True, "optimistic version conflict")

        def proposal():
            task = service.create_task(owner, CreateTask(goal="SQL verification: repairable desk light"))
            service.run_task(owner, task["id"])
            result = service.prepare(owner, task["id"], PrepareProposal(product_id="arc-light"))
            service.decide(owner, result["id"], Decision(decision="approve", terms_digest=result["terms_digest"]))
            return task, result

        task, first = proposal()
        _, competing = proposal()
        before = service.dashboard(owner)["budget"]["available_minor"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            actions = list(executor.map(lambda _: service.execute(owner, first["id"]), range(2)))
        check(actions[0]["id"] == actions[1]["id"], "concurrent duplicate execution returns one cart")
        try:
            service.execute(owner, competing["id"])
            raise AssertionError("stale competing proposal executed")
        except Problem:
            check(True, "competing stale proposal rejected")
        with store.transaction(owner) as unit:
            check(len(unit.all("actions")) == 1 and len(unit.all("reservations")) == 1,
                  "one atomic action and reservation")
        check(service.dashboard(owner)["budget"]["available_minor"] == before - actions[0]["total_minor"],
              "reservation reduces allowance exactly once")
        service.remove_cart(owner, actions[0]["id"])
        service.remove_cart(owner, actions[0]["id"])
        check(service.dashboard(owner)["budget"]["available_minor"] == before, "idempotent reservation release")

        imported = service.documents.import_bill(owner, SourceImport(text=service.documents.sample_bill()))
        request = BillConfirmation(**imported["fields"])
        confirmed = service.documents.confirm_bill(owner, imported["id"], request)
        repeated = service.documents.confirm_bill(owner, imported["id"], request)
        check(repeated["duplicate"] and confirmed["bill"]["id"] == repeated["bill"]["id"], "bill confirmation deduplication")

        run = service.scan(owner, guild_run_id=owner)
        retry = service.scan(owner, guild_run_id=owner)
        check(run["run_id"] == retry["run_id"], "backend scan redelivery uses the same run")
        restarted = AgentService(Store(settings), settings)
        check(restarted.detail(owner, task["id"])["task"]["status"] == "completed", "state survives a new service instance")
        checks = ["connection", "ownership", "large_unicode_payload", "rollback", "optimistic_versions", "concurrency", "atomic_reservation",
                  "release", "bill_deduplication", "scan_redelivery", "persistence"]
    finally:
        # Delete only this invocation's synthetic owner. Never clear demo-user.
        connection = store.connect()
        try:
            cursor = connection.cursor()
            cursor.execute("START TRANSACTION")
            for table in TABLES:
                cursor.execute(f"DELETE FROM {table} WHERE user_id=%s", (owner,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            service.ranker.close()
            if hasattr(service.evidence, "close"):
                service.evidence.close()
    report = {"result": "passed", "backend": "singlestore", "checks": checks,
              "synthetic_records_removed": True, "hosted_guild_execution_verified": False}
    (ROOT / ".local").mkdir(exist_ok=True)
    (ROOT / ".local/singlestore-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        frames = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                  for frame in traceback.extract_tb(exc.__traceback__)]
        print(json.dumps({"error_class": type(exc).__name__, "error_code": getattr(exc, "errno", None),
                          "frames": frames}))
        raise SystemExit(1)
