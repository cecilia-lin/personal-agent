"""Bounded, read-only inspection of this application's configured Cognee tenant."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = dotenv_values(ROOT / ".env")
    base = (env.get("COGNEE_BASE_URL") or "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".cognee.ai") or parsed.username or parsed.query:
        raise ValueError("Use the configured HTTPS Cognee tenant URL")
    with httpx.Client(timeout=httpx.Timeout(25, connect=5), follow_redirects=False,
                      headers={"X-Api-Key": env.get("COGNEE_API_KEY", "")}) as client:
        response = client.get(base + "/openapi.json")
        response.raise_for_status()
    result = response.json()
    destination = ROOT / ".local/cognee-job-discovery"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "tenant-openapi.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": response.status_code, "paths": list(result.get("paths", {}))}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error_class": type(exc).__name__}))
        raise SystemExit(1)
