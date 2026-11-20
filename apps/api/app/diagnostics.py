"""Read connectivity by default; --init-schema explicitly creates the schema."""
import argparse
from app.config import Settings
from app.repositories.store import Store

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-schema", action="store_true")
    parser.add_argument("--print-schema", action="store_true")
    args = parser.parse_args()
    store = Store(Settings.from_env())
    if args.print_schema:
        print(";\n".join(store.schema_sql()) + ";")
        return
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
