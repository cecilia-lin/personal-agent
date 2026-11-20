import os
from app.integrations import amplitude_client, statsig_client

def integration_status(settings, database_healthy=True, evidence=None, ranker=None):
    sql_configured = all(os.getenv(name) for name in (
        "SINGLESTORE_HOST", "SINGLESTORE_USER", "SINGLESTORE_PASSWORD", "SINGLESTORE_DATABASE"))
    sql_selected = settings.db_backend == "singlestore"
    guild_token = bool(os.getenv("BACKGROUND_TOOL_TOKEN") or os.getenv("GUILD_BACKEND_TOKEN"))
    result = [
        {"name": "SQLite", "status": "healthy" if settings.db_backend == "sqlite" and database_healthy else "disabled",
         "detail": "Durable local demo state." if settings.db_backend == "sqlite" else "Not selected.", "verified": settings.db_backend == "sqlite" and database_healthy},
        {"name": "SingleStore", "status": ("healthy" if database_healthy else "error") if sql_selected else "disabled" if sql_configured else "not_configured",
         "detail": "Selected SQL connection; transaction parity requires separate verification." if sql_selected else
                   "SQL credentials are configured; SQLite remains selected." if sql_configured else
                   "Management key configured; SQL connection credentials are still required." if os.getenv("SINGLESTORE_API_KEY") else
                   "SQL adapter prepared; database connection credentials are required.",
         "verified": sql_selected and database_healthy},
        {"name": "Guild AI", "status": "disabled" if guild_token else "not_configured",
         "detail": "Authenticated backend scan is ready; Guild sign-in, a reachable endpoint and hosted execution remain unverified." if guild_token else
                   "Backend scan prepared; configure its bearer credential and connect a Guild workspace.",
         "verified": False},
        {"name": "Model / merchant", "status": "demo" if settings.mode == "demo" else "not_configured",
         "detail": "Local task planning and persisted simulated cart; optional live relevance scoring is reported separately." if settings.mode == "demo" else "Live merchant and identity are not implemented; operations are blocked.", "verified": settings.mode == "demo"},
    ]
    for name, key, detail, default in [
        ("Cognee", "COGNEE_API_KEY", "Optional preference-memory interface only.", "disabled"),
    ]:
        configured = bool(os.getenv(key))
        result.append({"name": name, "status": "disabled" if configured else default,
                       "detail": detail + (" A credential is present but is not used by this build." if configured else ""),
                       "verified": False})
    result.extend([amplitude_client.status(), statsig_client.status()])
    result.append(ranker.status() if ranker else {
        "name": "Superlinked SIE", "status": "not_configured", "verified": False,
        "detail": "Live relevance scoring has not been configured.",
    })
    result.append(evidence.status() if hasattr(evidence, "status") else {
        "name": "Senso", "status": "not_configured", "verified": False,
        "detail": "Using fixture passages. Set SENSO_API_KEY in .env and restart for live context.",
    })
    return result
