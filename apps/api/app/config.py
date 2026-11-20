from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
DEMO_USER = "demo-user"

@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    db_backend: str = "sqlite"
    sqlite_path: Path = ROOT / "data/personal-agent.db"
    routing_policy: str = "specialist_first"

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        mode = os.getenv("APP_MODE", "demo")
        backend = os.getenv("DB_BACKEND", "sqlite")
        policy = os.getenv("LOCAL_ROUTING_POLICY", "specialist_first")
        if mode not in {"demo", "live"} or backend not in {"sqlite", "singlestore"}:
            raise ValueError("APP_MODE must be demo|live; DB_BACKEND must be sqlite|singlestore.")
        if policy not in {"specialist_first", "general_model_first"}:
            raise ValueError("Unknown LOCAL_ROUTING_POLICY.")
        path = Path(os.getenv("SQLITE_PATH", "data/personal-agent.db"))
        return cls(mode, backend, path if path.is_absolute() else ROOT / path, policy)
