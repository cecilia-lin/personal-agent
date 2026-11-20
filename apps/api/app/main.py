from contextlib import asynccontextmanager
from hmac import compare_digest
import os
from pathlib import Path
from fastapi import FastAPI, Depends, Header, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import DEMO_USER, Settings
from app.domain.models import (CreateTask, PrepareProposal, Decision, BudgetEdit,
    BillEdit, QuoteEdit, PreferenceEdit, Problem, SourceImport, BillConfirmation, SaveWatch)
from app.repositories.store import Store
from app.services.agent import AgentService
from app.integrations.status import integration_status
from app.integrations import amplitude_client, statsig_client

def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    store = Store(settings)
    service = AgentService(store, settings)

    @asynccontextmanager
    async def lifespan(app):
        amplitude_client.initialize()
        statsig_client.initialize()
        if hasattr(service.evidence, "check_connection"):
            service.evidence.check_connection()
        app.state.database_ready = False
        try:
            store.initialize()
            app.state.database_ready = True
            if settings.mode == "demo":
                service.seed()
        except Exception as exc:
            app.state.database_ready = False
            # Exception classes are safe to report; driver messages may contain credentials.
            app.state.database_error = f"Database startup failed ({type(exc).__name__}). Run the documented diagnostic."
        try:
            yield
        finally:
            if hasattr(service.evidence, "close"):
                service.evidence.close()
            service.ranker.close()
            statsig_client.shutdown()
            amplitude_client.shutdown()

    app = FastAPI(title="Intent", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store, app.state.service = store, service

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    def actor(x_demo_user: str = Header(default=DEMO_USER)):
        if settings.mode != "demo":
            raise Problem("Live authentication is not implemented. Demo operations are unavailable.", 503)
        if x_demo_user != DEMO_USER:
            raise Problem("This local app only supports the explicitly identified demo-user.", 403)
        if not app.state.database_ready:
            raise Problem(getattr(app.state, "database_error", "Database unavailable."), 503)
        return DEMO_USER

    @app.get("/api/health")
    def health():
        database_ready = app.state.database_ready
        if database_ready:
            try:
                database_ready = store.diagnostic()
            except Exception:
                database_ready = False
        ready = database_ready and settings.mode == "demo"
        return JSONResponse(status_code=200 if ready else 503, content={
            "ready": ready, "mode": settings.mode, "database": settings.db_backend,
            "database_ready": database_ready,
            "detail": "Local demo ready." if ready else "Check database configuration; live adapters and authentication are not implemented.",
        })

    @app.get("/api/integrations")
    def integrations():
        return {"integrations": integration_status(settings, app.state.database_ready, service.evidence, service.ranker)}

    @app.post("/api/research-memory/recall")
    def research_memory(user=Depends(actor)):
        from app.services.research_memory import get_research_memory
        root = Path(__file__).resolve().parents[3]
        output = Path(os.getenv("COGNEE_PREPARATION_OUTPUT", str(root / ".local/cognee-job-smoke")))
        return get_research_memory(output)

    @app.post("/api/demo/seed")
    def seed(user=Depends(actor)):
        return service.seed()

    @app.post("/api/demo/reset")
    def reset(user=Depends(actor)):
        return service.seed(reset=True)

    @app.get("/api/dashboard")
    def dashboard(user=Depends(actor)):
        return service.dashboard(user)

    @app.post("/api/tasks", status_code=201)
    def create_task(request: CreateTask, user=Depends(actor)):
        return service.create_task(user, request)

    @app.post("/api/tasks/{task_id}/run")
    def run_task(task_id: str, user=Depends(actor)):
        return service.run_task(user, task_id)

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str, user=Depends(actor)):
        return service.detail(user, task_id)

    @app.get("/api/tasks/{task_id}/audit")
    def task_audit(task_id: str, user=Depends(actor)):
        return {"audit": service.detail(user, task_id)["audit"]}

    @app.post("/api/tasks/{task_id}/proposals", status_code=201)
    def prepare(task_id: str, request: PrepareProposal, user=Depends(actor)):
        return service.prepare(user, task_id, request)

    @app.post("/api/proposals/{proposal_id}/decision")
    def decide(proposal_id: str, request: Decision, user=Depends(actor)):
        return service.decide(user, proposal_id, request)

    @app.post("/api/proposals/{proposal_id}/execute")
    def execute(proposal_id: str, user=Depends(actor)):
        return service.execute(user, proposal_id)

    @app.get("/api/actions/{action_id}")
    def get_action(action_id: str, user=Depends(actor)):
        with store.transaction(user) as unit:
            return unit.get("actions", action_id)

    @app.patch("/api/demo/budget")
    def edit_budget(request: BudgetEdit, user=Depends(actor)):
        return service.edit(user, "accounts", "cash", request.model_dump())

    @app.patch("/api/demo/bills/{bill_id}")
    def edit_bill(bill_id: str, request: BillEdit, user=Depends(actor)):
        return service.edit(user, "bills", bill_id, request.model_dump())

    @app.patch("/api/demo/products/{product_id}")
    def edit_quote(product_id: str, request: QuoteEdit, user=Depends(actor)):
        return service.edit(user, "products", product_id, request.model_dump())

    @app.patch("/api/demo/preferences")
    def edit_preferences(request: PreferenceEdit, user=Depends(actor)):
        return service.edit(user, "preferences", "shopping", request.model_dump())

    @app.post("/api/background/scan")
    def scan(limit: int = Query(default=5, ge=1, le=10), user=Depends(actor)):
        return service.scan(user, limit)


    @app.post("/api/imports/email")
    def import_email(request: SourceImport, user=Depends(actor)):
        return service.documents.import_email(user, request)

    @app.post("/api/imports/bill")
    def import_bill(request: SourceImport, user=Depends(actor)):
        return service.documents.import_bill(user, request)

    @app.post("/api/imports/bill/{import_id}/confirm")
    def confirm_bill(import_id: str, request: BillConfirmation, user=Depends(actor)):
        return service.documents.confirm_bill(user, import_id, request)

    @app.get("/api/bills/{bill_id}/history")
    def bill_history(bill_id: str, user=Depends(actor)):
        with store.transaction(user) as unit:
            current = unit.get("bills", bill_id)
            history = [b for b in unit.all("bill_history") if b["id"].startswith(bill_id + "_v")]
            return {"current": current, "history": history}

    @app.get("/api/sources/{source_id}")
    def get_source(source_id: str, user=Depends(actor)):
        with store.transaction(user) as unit:
            return unit.get("sources", source_id)

    @app.post("/api/actions/{action_id}/remove")
    def remove_cart(action_id: str, user=Depends(actor)):
        return service.remove_cart(user, action_id)

    @app.post("/api/next-actions/{next_id}/acknowledge")
    def acknowledge(next_id: str, user=Depends(actor)):
        with store.transaction(user, write=True) as unit:
            item = unit.get("next_actions", next_id)
            if item["status"] == "acknowledged":
                return item
            return unit.save("next_actions", next_id, {**item, "status": "acknowledged"}, item["version"])


    @app.post("/api/tasks/{task_id}/watch")
    def save_watch(task_id: str, request: SaveWatch, user=Depends(actor)):
        return service.intent.save_watch(user, task_id, request.product_id)

    @app.get("/api/watchlist")
    def watchlist(user=Depends(actor)):
        with store.transaction(user) as unit:
            return {"items": unit.all("watch_items")}

    @app.post("/api/watchlist/{watch_id}/archive")
    def archive_watch(watch_id: str, user=Depends(actor)):
        with store.transaction(user, write=True) as unit:
            item = unit.get("watch_items", watch_id)
            if item["status"] == "archived":
                return item
            return unit.save("watch_items", watch_id, {**item, "status": "archived"}, item["version"])

    @app.get("/api/products/{product_id}/history")
    def price_history(product_id: str, user=Depends(actor)):
        with store.transaction(user) as unit:
            unit.get("products", product_id)
            return {"observations": service.intent.history(unit, product_id), "provenance": "fixture",
                    "notice": "Timestamped synthetic observations, not a forecast or live price history."}

    bearer = HTTPBearer(auto_error=False)

    @app.post("/api/guild/scan", operation_id="review_due_tasks")
    def guild_scan(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                   limit: int = Query(default=5, ge=1, le=10),
                   guild_run_id: str = Query(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")):
        expected = os.getenv("BACKGROUND_TOOL_TOKEN") or os.getenv("GUILD_BACKEND_TOKEN", "")
        if not expected:
            raise Problem("BACKGROUND_TOOL_TOKEN is not configured.", 503)
        if credentials is None or not compare_digest(credentials.credentials, expected):
            raise Problem("A valid backend bearer token is required.", 401)
        actor(DEMO_USER)
        return service.scan(DEMO_USER, limit, guild_run_id=guild_run_id)

    @app.get("/api/guild/openapi.json", include_in_schema=False)
    def guild_openapi():
        schema = app.openapi()
        return {**schema, "paths": {"/api/guild/scan": schema["paths"]["/api/guild/scan"]}}

    return app

app = create_app()
