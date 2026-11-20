"""Owned, versioned SQL records. SQLite and SingleStore dialects stay here."""
from contextlib import contextmanager
import json
import os
import sqlite3
from app.config import Settings
from app.domain.models import Problem

TABLES = (
    "accounts", "bills", "preferences", "sessions", "tasks", "products",
    "proposals", "actions", "audit_events", "analytics_events", "holdings",
    "sources", "source_versions", "offers", "merchant_offers", "bill_imports", "bill_history",
    "reservations", "next_actions", "runs", "adjustments", "watch_items", "price_history",
)

class UnitOfWork:
    def __init__(self, connection, backend: str, user_id: str):
        self.connection, self.backend, self.user_id = connection, backend, user_id
        self.after_commit = []

    def execute(self, sql: str, params=()):
        cursor = self.connection.cursor()
        cursor.execute(sql.replace("?", "%s") if self.backend == "singlestore" else sql, params)
        return cursor

    def table(self, name):
        if name not in TABLES:
            raise ValueError("Unknown table")
        return name

    def get(self, table, record_id, required=True):
        row = self.execute(
            f"SELECT id, version, payload FROM {self.table(table)} WHERE user_id=? AND id=?",
            (self.user_id, record_id),
        ).fetchone()
        if row is None:
            if required:
                raise Problem("Record not found for the current user.", 404)
            return None
        return {**json.loads(row[2]), "id": row[0], "version": row[1], "user_id": self.user_id}

    def all(self, table):
        rows = self.execute(
            f"SELECT id, version, payload FROM {self.table(table)} WHERE user_id=? ORDER BY id",
            (self.user_id,),
        ).fetchall()
        return [{**json.loads(r[2]), "id": r[0], "version": r[1], "user_id": self.user_id} for r in rows]

    def save(self, table, record_id, payload, expected_version=None):
        payload = {k: v for k, v in payload.items() if k not in {"id", "version", "user_id"}}
        encoded = json.dumps(payload, sort_keys=True)
        if expected_version is None:
            self.execute(
                f"INSERT INTO {self.table(table)} (user_id,id,version,payload) VALUES (?,?,1,?)",
                (self.user_id, record_id, encoded),
            )
        else:
            result = self.execute(
                f"UPDATE {self.table(table)} SET payload=?, version=version+1 WHERE user_id=? AND id=? AND version=?",
                (encoded, self.user_id, record_id, expected_version),
            )
            if result.rowcount != 1:
                raise Problem("The record changed. Refresh before trying again.")
        return self.get(table, record_id)

    def clear_demo(self):
        if self.user_id != "demo-user":
            raise Problem("Only demo-owned records may be reset.", 403)
        for table in TABLES:
            self.execute(f"DELETE FROM {table} WHERE user_id=?", (self.user_id,))

class Store:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self):
        if self.settings.db_backend == "sqlite":
            self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.settings.sqlite_path, timeout=15)
            connection.execute("PRAGMA busy_timeout=15000")
            return connection
        import singlestoredb
        names = ["SINGLESTORE_HOST", "SINGLESTORE_USER", "SINGLESTORE_PASSWORD", "SINGLESTORE_DATABASE"]
        missing = [name for name in names if not os.getenv(name)]
        if missing:
            raise RuntimeError("SingleStore configuration missing: " + ", ".join(missing))
        return singlestoredb.connect(
            host=os.environ["SINGLESTORE_HOST"], user=os.environ["SINGLESTORE_USER"],
            password=os.environ["SINGLESTORE_PASSWORD"], database=os.environ["SINGLESTORE_DATABASE"],
            port=int(os.getenv("SINGLESTORE_PORT", "3306")), autocommit=False,
            ssl_verify_cert=True, ssl_verify_identity=True, connect_timeout=5,
            results_type="tuples",
        )

    def schema_sql(self):
        prefix = "CREATE ROWSTORE TABLE" if self.settings.db_backend == "singlestore" else "CREATE TABLE"
        shard = ", SHARD KEY (user_id)" if self.settings.db_backend == "singlestore" else ""
        # Task checkpoints and escaped document text can exceed MySQL TEXT's 64 KiB limit.
        payload_type = "LONGTEXT" if self.settings.db_backend == "singlestore" else "TEXT"
        return [
            f"{prefix} IF NOT EXISTS {table} (user_id VARCHAR(128) NOT NULL, id VARCHAR(128) NOT NULL, "
            f"version BIGINT NOT NULL, payload {payload_type} NOT NULL, PRIMARY KEY (user_id,id){shard})"
            for table in TABLES
        ]

    def initialize(self):
        connection = self.connect()
        try:
            for statement in self.schema_sql():
                connection.cursor().execute(statement)
            if self.settings.db_backend == "singlestore":
                cursor = connection.cursor()
                cursor.execute("SELECT TABLE_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                               "WHERE TABLE_SCHEMA=DATABASE() AND COLUMN_NAME='payload'")
                for table, data_type in cursor.fetchall():
                    if table in TABLES and data_type.lower() in {"tinytext", "text", "mediumtext"}:
                        # A widening migration preserves records from the initial schema.
                        connection.cursor().execute(f"ALTER TABLE {table} MODIFY COLUMN payload LONGTEXT NOT NULL")
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self, user_id: str, write=False):
        connection = self.connect()
        unit = UnitOfWork(connection, self.settings.db_backend, user_id)
        try:
            unit.execute("BEGIN IMMEDIATE" if write and self.settings.db_backend == "sqlite" else
                         "BEGIN" if self.settings.db_backend == "sqlite" else "START TRANSACTION")
            if write and self.settings.db_backend == "singlestore":
                # One account row serializes all financial mutations for this owner.
                unit.execute("SELECT id FROM accounts WHERE user_id=? AND id=? FOR UPDATE",
                             (user_id, "cash")).fetchone()
            yield unit
            connection.commit()
            for callback in unit.after_commit:
                try:
                    callback()
                except Exception:
                    # Telemetry is best effort and cannot undo a committed domain action.
                    pass
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def diagnostic(self):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
        finally:
            connection.close()
