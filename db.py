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


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def parse_tags(text):
    """Turn "Dinner, quick,, dinner " into ["dinner", "quick"].

    Trims spaces, lowercases, skips blanks and drops duplicates (keeping order).
    """
    tags = []
    for piece in text.split(","):
        tag = piece.strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _save_tags(conn, recipe_id, tags):
    """Link a recipe to its tags, creating any tag that doesn't exist yet."""
    for tag in tags:
        # INSERT OR IGNORE: skip quietly if the tag name already exists (it's UNIQUE)
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO recipe_tags (recipe_id, tag_id) VALUES (?, ?)",
            (recipe_id, tag_id),
        )


def _tags_for(conn, recipe_id):
    """Tag names for one recipe, alphabetical."""
    rows = conn.execute(
        "SELECT tags.name FROM tags"
        " JOIN recipe_tags ON recipe_tags.tag_id = tags.id"
        " WHERE recipe_tags.recipe_id = ? ORDER BY tags.name",
        (recipe_id,),
    )
    return [row["name"] for row in rows]


def _save_ingredients(conn, recipe_id, ingredients):
    """Save ingredient dicts ({"amount", "unit", "name"}) in the order given."""
    for position, ing in enumerate(ingredients):
        conn.execute(
            "INSERT INTO ingredients (recipe_id, position, amount, unit, name)"
            " VALUES (?, ?, ?, ?, ?)",
            (recipe_id, position, ing.get("amount", ""), ing.get("unit", ""), ing["name"]),
        )


# ---------------------------------------------------------------------------
# Recipes: create / read / update / delete
# ---------------------------------------------------------------------------

def create_recipe(name, servings, ingredients, steps, tags, db_path=DEFAULT_DB_PATH):
    """Add a new recipe and return its id.

    ingredients: list of {"amount": "1/3", "unit": "cup", "name": "flour"}
    steps: one string, one step per line
    tags: list of tag names (already cleaned by parse_tags)
    """
    conn = get_connection(db_path)
    try:
        # "with conn" saves everything at the end, or nothing if an error happens
        with conn:
            cursor = conn.execute(
                "INSERT INTO recipes (name, servings, steps) VALUES (?, ?, ?)",
                (name, servings, steps),
            )
            recipe_id = cursor.lastrowid
            _save_ingredients(conn, recipe_id, ingredients)
            _save_tags(conn, recipe_id, tags)
        return recipe_id
    finally:
        conn.close()


def get_recipe(recipe_id, db_path=DEFAULT_DB_PATH):
    """Return one recipe as a dict (with ingredients and tags), or None if not found."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return None
        recipe = dict(row)
        ingredient_rows = conn.execute(
            "SELECT amount, unit, name FROM ingredients WHERE recipe_id = ? ORDER BY position",
            (recipe_id,),
        )
        recipe["ingredients"] = [dict(r) for r in ingredient_rows]
        recipe["tags"] = _tags_for(conn, recipe_id)
        return recipe
    finally:
        conn.close()


def list_recipes(db_path=DEFAULT_DB_PATH):
    """Return all recipes (id, name, servings, tags), sorted by name."""
    conn = get_connection(db_path)
    try:
        recipes = []
        for row in conn.execute("SELECT id, name, servings FROM recipes ORDER BY name"):
            recipe = dict(row)
            recipe["tags"] = _tags_for(conn, recipe["id"])
            recipes.append(recipe)
        return recipes
    finally:
        conn.close()


def update_recipe(recipe_id, name, servings, ingredients, steps, tags, db_path=DEFAULT_DB_PATH):
    """Replace a recipe's details, ingredients and tags with the new values."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE recipes SET name = ?, servings = ?, steps = ? WHERE id = ?",
                (name, servings, steps, recipe_id),
            )
            # Simplest approach: wipe the old ingredients and tag links, then save the new ones
            conn.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
            conn.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
            _save_ingredients(conn, recipe_id, ingredients)
            _save_tags(conn, recipe_id, tags)
    finally:
        conn.close()


def delete_recipe(recipe_id, db_path=DEFAULT_DB_PATH):
    """Delete a recipe. ON DELETE CASCADE also removes its ingredients and tag links."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    finally:
        conn.close()
