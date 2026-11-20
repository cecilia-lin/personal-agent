"""Regenerate dialect-specific SQL and the narrow Guild OpenAPI contract."""
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"apps/api"))
os.environ["INTEGRATIONS_ENABLED"]="false"
from app.config import Settings
from app.repositories.store import Store
from app.main import create_app
(ROOT/"migrations").mkdir(exist_ok=True)
for backend in ("sqlite","singlestore"):
    sql=";\n".join(Store(Settings(db_backend=backend)).schema_sql())+";\n"
    (ROOT/f"migrations/001_{backend}.sql").write_text(sql,encoding="utf-8")
schema=create_app(Settings()).openapi()
schema["info"]={"title":"Intent background tools","version":"0.1.0",
 "description":"Authenticated bounded watchlist and utility reminder checks. No spending operations."}
schema["paths"]={"/api/guild/scan":schema["paths"]["/api/guild/scan"]}
schema["components"]["schemas"]={k:v for k,v in schema["components"]["schemas"].items()
    if k in {"HTTPValidationError","ValidationError"}}
schema["paths"]["/api/guild/scan"]["post"]["description"]="Recheck watchlists and utility reminders; reuse guild_run_id on redelivery. Does not create a cart."
(ROOT/"docs/guild").mkdir(exist_ok=True)
(ROOT/"docs/guild/openapi.json").write_text(json.dumps(schema,indent=2)+"\n",encoding="utf-8")
print("Generated SQLite and SingleStore DDL plus one authenticated Guild operation.")
