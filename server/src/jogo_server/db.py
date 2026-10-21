"""SQLite: one connection for the one process, WAL, foreign keys, migrations by PRAGMA user_version."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    # autocommit (each statement is its own transaction) unless inside tx(); only the event loop's thread uses
    # it, the TestClient's portal thread included, hence check_same_thread=False
    db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")  # the backup job's sqlite3 .backup may hold a lock briefly
    migrate(db)
    return db


def migrate(db: sqlite3.Connection) -> None:
    have = db.execute("PRAGMA user_version").fetchone()[0]
    parts = re.split(r"^-- migration (\d+)$", SCHEMA.read_text(encoding="utf-8"), flags=re.M)
    for n, sql in zip(parts[1::2], parts[2::2], strict=True):
        if int(n) > have:
            db.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {int(n)};\nCOMMIT;")


@contextmanager
def tx(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Several statements as one: all or none."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
