"""Tests never load live provider credentials or emit external analytics."""
import os

import pytest

ISOLATED_KEYS = ("AMPLITUDE_API_KEY", "STATSIG_SERVER_SECRET", "STATSIG_SERVER_SECRET_KEY",
                 "SENSO_API_KEY", "SIE_API_KEY", "COGNEE_API_KEY", "COGNEE_BASE_URL",
                 "BACKGROUND_TOOL_TOKEN", "GUILD_BACKEND_TOKEN")

# Set these before test modules import app.main. dotenv preserves existing values.
for name in ISOLATED_KEYS:
    os.environ[name] = ""


@pytest.fixture(autouse=True)
def no_external_integrations(monkeypatch):
    for name in ISOLATED_KEYS:
        monkeypatch.setenv(name, "")

os.environ["INTEGRATIONS_ENABLED"] = "false"


@pytest.fixture
def senso_runtime_ledger():
    import hashlib
    return {"schema_version": "intent-senso-corpus-v1", "products": {"arc-light": {
        "status": "ready", "content_id": "content-1", "kb_node_id": "node-1", "version_id": "version-3",
        "content_hash": hashlib.sha256(b"Arc Light is repairable.").hexdigest()}}}
