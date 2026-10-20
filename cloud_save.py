"""Keep the recipes safe when the app is hosted on Render's free plan.

Render's free web service wipes its files every time it restarts (and it
restarts after 15 minutes without visitors), so recipes.db would be lost.
So when DATABASE_URL is set (Render sets it), the app:

  1. on startup, copies the database back from Render's free Postgres,
  2. after every change (any form you submit), saves a fresh copy there.

The app itself keeps using SQLite as always; Postgres just holds one copy
of the whole recipes.db file. The free Postgres expires after 30 days, so
if it's empty (say you made a new one), the recipes are reloaded from your
JSON backup (the file from "Export") uploaded to Render as a Secret File.

Locally DATABASE_URL isn't set, so none of this runs. Setup steps: RENDER.md
"""

import os
import sqlite3
from pathlib import Path

import db
import importer

# Render puts Secret Files here. Change it with the RESTORE_FILE setting.
DEFAULT_BACKUP_FILE = "/etc/secrets/recipes-backup.json"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS saved_copy (
    id       INTEGER PRIMARY KEY,   -- always 1: there's only one copy
    data     BYTEA NOT NULL,        -- the whole recipes.db file
    saved_at TIMESTAMPTZ NOT NULL
)
"""


class PostgresStore:
    """Saves and loads the one database copy in Postgres."""

    def __init__(self, url):
        self.url = url

    def _connect(self):
        import psycopg   # only needed on Render, so it's imported here
        return psycopg.connect(self.url, connect_timeout=15)

    def load(self):
        """The saved database file as bytes, or None if nothing is saved yet."""
        # "with" saves the changes (here: creating the table) when it's done
        with self._connect() as conn:
            conn.execute(CREATE_TABLE)
            row = conn.execute("SELECT data FROM saved_copy WHERE id = 1").fetchone()
        return bytes(row[0]) if row else None

    def save(self, data):
        """Replace the saved copy with data (bytes)."""
        with self._connect() as conn:
            conn.execute(CREATE_TABLE)
            conn.execute(
                "INSERT INTO saved_copy (id, data, saved_at) VALUES (1, %s, now())"
                " ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, saved_at = now()",
                (data,),
            )


def store_from_env():
    """A PostgresStore when DATABASE_URL is set (on Render), otherwise None."""
    url = os.environ.get("DATABASE_URL", "")
    return PostgresStore(url) if url else None


def restore_on_startup(db_path, store, backup_file=None):
    """Bring the recipes back before the app starts. Returns what it did.

    "saved copy":  copied the database back from Postgres
    "backup file": Postgres was empty, so the JSON backup was loaded
    "nothing":     neither had anything (a brand-new app starts with the samples)

    If Postgres can't be reached this raises, so the app doesn't start: an
    app started empty would save over your good copy with the next change.
    """
    data = store.load()
    if data:
        Path(db_path).write_bytes(data)
        return "saved copy"

    backup = Path(backup_file or os.environ.get("RESTORE_FILE") or DEFAULT_BACKUP_FILE)
    if not backup.is_file():
        return "nothing"
    db.init_db(db_path)
    if db.count_recipes(db_path) > 0:
        return "nothing"   # there are recipes already; never add the backup twice
    recipes, errors = importer.parse_json_text(backup.read_text(encoding="utf-8"))
    if errors:
        # Stop here rather than start with the sample recipes: those would be
        # saved to Postgres, and then the backup would never be loaded
        raise RuntimeError(f"The backup file {backup} can't be read: {errors[0]}")
    importer.save_recipes(recipes, save_anyway=range(len(recipes)), db_path=db_path)
    return "backup file"


def save_now(db_path, store):
    """Save a copy of the whole database file to the store."""
    conn = sqlite3.connect(db_path)
    try:
        data = conn.serialize()   # the database file's bytes, read safely
    finally:
        conn.close()
    store.save(data)
