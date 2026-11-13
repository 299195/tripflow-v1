from __future__ import annotations

import sqlite3
from pathlib import Path


class SqliteDatabase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        # FastAPI runs synchronous handlers in worker threads. The app serializes
        # requests around this single connection (V1 single-user runtime).
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def migrate(self) -> None:
        migration_dir = Path(__file__).with_name("migrations")
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for file in sorted(migration_dir.glob("*.sql")):
            version = int(file.name.split("_", 1)[0])
            if self.connection.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone():
                continue
            self.connection.executescript(file.read_text(encoding="utf-8"))
            self.connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))", (version,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
