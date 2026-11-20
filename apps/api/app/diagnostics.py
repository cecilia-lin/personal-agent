"""Read connectivity by default; --init-schema explicitly creates the schema."""
import argparse
from dataclasses import replace
import json
import os
from app.config import Settings
from app.repositories.store import Store


def check_singlestore_management():
    """Read resource metadata only; management access does not prove SQL access."""
    key = os.getenv("SINGLESTORE_API_KEY", "").strip()
    if not key:
        print("SingleStore management: set SINGLESTORE_API_KEY in .env.")
        return False
    import singlestoredb

    # Bound this one-shot diagnostic without changing shell configuration.
    os.environ.setdefault("SINGLESTOREDB_MANAGEMENT_CONNECT_TIMEOUT", "5")
    os.environ.setdefault("SINGLESTOREDB_MANAGEMENT_READ_TIMEOUT", "15")
    os.environ.setdefault("SINGLESTOREDB_MANAGEMENT_RETRIES", "0")
    try:
        manager = singlestoredb.manage_clusters(access_token=key, version="v2")
        result = {
            "management_access_verified": True,
            "sql_access_verified": False,
            "clusters": [{"name": item.name, "state": item.state,
                          "endpoint": item.endpoint} for item in manager.clusters],
            "starter_clusters": [{"name": item.name, "endpoint": item.endpoint,
                                  "database": item.database_name} for item in manager.starter_clusters],
        }
        print(json.dumps(result, indent=2))
        print("SQL needs an active endpoint and SINGLESTORE_HOST, SINGLESTORE_USER, "
              "SINGLESTORE_PASSWORD, SINGLESTORE_DATABASE. No resources were changed.")
        return True
    except Exception as exc:
        print(f"SingleStore management failed ({type(exc).__name__}); check key scope and network access.")
        return False


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--init-schema", action="store_true")
    actions.add_argument("--print-schema", action="store_true")
    actions.add_argument("--singlestore-management", action="store_true")
    parser.add_argument("--backend", choices=("sqlite", "singlestore"))
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.singlestore_management:
        raise SystemExit(0 if check_singlestore_management() else 1)
    store = Store(replace(settings, db_backend=args.backend) if args.backend else settings)
    if args.print_schema:
        print(";\n".join(store.schema_sql()) + ";")
        return
    if store.settings.db_backend == "singlestore":
        missing = [name for name in ("SINGLESTORE_HOST", "SINGLESTORE_USER", "SINGLESTORE_PASSWORD", "SINGLESTORE_DATABASE")
                   if not os.getenv(name)]
        if missing:
            print("SingleStore SQL configuration missing: " + ", ".join(missing))
            print("SINGLESTORE_API_KEY is for management; it is not a SQL password.")
            raise SystemExit(1)
    try:
        if args.init_schema:
            store.initialize()
        print(f"{store.settings.db_backend}: SELECT 1 verified={store.diagnostic()}")
    except Exception as exc:
        # Never print a provider's potentially credential-bearing error message.
        print(f"{store.settings.db_backend}: connection failed ({type(exc).__name__}). Check the documented environment settings, database grants, TLS, and network access.")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
