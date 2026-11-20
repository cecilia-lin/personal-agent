import os
from app.integrations import amplitude_client, statsig_client

def integration_status(settings, database_healthy=True, evidence=None, ranker=None):
    result = [
        {"name": "SQLite", "status": "healthy" if settings.db_backend == "sqlite" and database_healthy else "disabled",
         "detail": "Durable local demo state." if settings.db_backend == "sqlite" else "Not selected.", "verified": settings.db_backend == "sqlite" and database_healthy},
        {"name": "SingleStore", "status": ("healthy" if database_healthy else "error") if settings.db_backend == "singlestore" else "not_configured",
         "detail": "SQL adapter and schema prepared; a successful selected connection verifies connectivity only.", "verified": settings.db_backend == "singlestore" and database_healthy},
        {"name": "Model / merchant", "status": "demo" if settings.mode == "demo" else "not_configured",
         "detail": "Local task planning and persisted simulated cart; optional live relevance scoring is reported separately." if settings.mode == "demo" else "Live merchant and identity are not implemented; operations are blocked.", "verified": settings.mode == "demo"},
    ]
    for name, key, detail, default in [
        ("Guild AI", "GUILD_API_KEY", "Authenticated scan endpoint prepared; no scheduler deployed.", "not_configured"),
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
