"""Small helpers for talking to the SQLite database."""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DEFAULT_DB_PATH = BASE_DIR / "recipes.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_connection(db_path=DEFAULT_DB_PATH):
    """Open a connection to the database.

    Rows come back as sqlite3.Row, so you can use row["name"] instead of row[1].
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # SQLite ignores foreign keys (like ON DELETE CASCADE) unless this is on
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=DEFAULT_DB_PATH):
    """Create the tables if they don't exist yet. Safe to run every startup."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
    finally:
        conn.close()
