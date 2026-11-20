"""Run the actual API with isolated synthetic state for live acceptance testing."""
import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--unavailable", action="store_true", help="Controlled missing-key case, never fixture fallback")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    os.environ.update(INTEGRATIONS_ENABLED="true", EVIDENCE_PROVIDER="senso", APP_MODE="demo", DB_BACKEND="sqlite",
                      AMPLITUDE_API_KEY="", STATSIG_SERVER_SECRET="", STATSIG_SERVER_SECRET_KEY="", SIE_API_KEY="")
    if args.unavailable:
        os.environ["SENSO_API_KEY"] = ""
    from app.config import Settings
    from app.main import create_app
    database = ROOT / ".local" / ("intent-unavailable-acceptance.db" if args.unavailable else "intent-live-acceptance.db")
    uvicorn.run(create_app(Settings(sqlite_path=database)), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
