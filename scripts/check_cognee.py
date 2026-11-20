"""Read-only Cognee Cloud key/workspace check. Does not ingest or search memory."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = dotenv_values(ROOT / ".env")
    key = config.get("COGNEE_API_KEY", "")
    if not key:
        print("Set COGNEE_API_KEY in the ignored root .env.")
        return 1
    with httpx.Client(headers={"X-Api-Key": key}, timeout=30, follow_redirects=False) as client:
        identity = client.get("https://api.aws.cognee.ai/api/v1/api-keys/my-user-id")
        identity.raise_for_status()
        base_url = config.get("COGNEE_BASE_URL")
        if not base_url:
            tenant = client.get("https://api.aws.cognee.ai/api/v1/tenants/current/service-url")
            tenant.raise_for_status()
            base_url = tenant.json()["service_url"]
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".cognee.ai")
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            print("Use the HTTPS workspace API base URL from Cognee Cloud's Connection panel.")
            return 1
        base_url = base_url.rstrip("/")
        datasets = client.get(base_url + "/api/v1/datasets/")
        datasets.raise_for_status()
        set_key(ROOT / ".env", "COGNEE_BASE_URL", base_url)
    result = {"api_key_verified": True, "workspace_access_verified": True,
              "dataset_endpoint_status": datasets.status_code,
              "memory_write_verified": False, "memory_recall_verified": False,
              "app_memory_integration_enabled": False}
    (ROOT / ".local").mkdir(exist_ok=True)
    (ROOT / ".local/cognee-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        print(f"Cognee check failed (HTTP {exc.response.status_code}); credentials and response bodies are hidden.")
        raise SystemExit(1)
    except Exception as exc:
        print(f"Cognee check failed ({type(exc).__name__}).")
        raise SystemExit(1)
