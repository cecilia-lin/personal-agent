"""Tests never load live provider credentials or emit external analytics."""
import os

import pytest

# Set these before test modules import app.main. dotenv preserves existing values.
for name in ("AMPLITUDE_API_KEY", "STATSIG_SERVER_SECRET", "SENSO_API_KEY", "SIE_API_KEY"):
    os.environ[name] = ""


@pytest.fixture(autouse=True)
def no_external_integrations(monkeypatch):
    for name in ("AMPLITUDE_API_KEY", "STATSIG_SERVER_SECRET", "SENSO_API_KEY", "SIE_API_KEY"):
        monkeypatch.setenv(name, "")

os.environ["INTEGRATIONS_ENABLED"] = "false"
