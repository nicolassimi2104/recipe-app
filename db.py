"""Small helpers for talking to the SQLite database."""

import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DEFAULT_DB_PATH = BASE_DIR / "recipes.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH = BASE_DIR / "recipes.json"


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


def import_seed_data(db_path=DEFAULT_DB_PATH, json_path=SEED_PATH):
    """Load the starter recipes from recipes.json, but only if there are no recipes yet.

    Returns how many recipes were imported (0 if the database already had some).
    """
    conn = get_connection(db_path)
    try:
        recipe_count = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    finally:
        conn.close()
    if recipe_count > 0:
        return 0

    # encoding="utf-8" so characters like ° and é read correctly on Windows
    with open(json_path, encoding="utf-8") as f:
        seed_recipes = json.load(f)

    for recipe in seed_recipes:
        create_recipe(
            name=recipe["name"],
            servings=recipe["servings"],
            ingredients=recipe["ingredients"],
            steps="\n".join(recipe["steps"]),  # the JSON has a list; the database stores lines
            tags=parse_tags(",".join(recipe["tags"])),  # same cleanup as the form
            db_path=db_path,
        )
    return len(seed_recipes)


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
    return search_recipes(db_path=db_path)


def count_recipes(db_path=DEFAULT_DB_PATH):
    """How many recipes there are in total."""
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    finally:
        conn.close()


def list_tags(db_path=DEFAULT_DB_PATH):
    """Names of all tags used by at least one recipe, alphabetical."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT tags.name FROM tags"
            " JOIN recipe_tags ON recipe_tags.tag_id = tags.id ORDER BY tags.name"
        )
        return [row["name"] for row in rows]
    finally:
        conn.close()


def _like_pattern(text):
    """Turn "chick" into "%chick%" for a LIKE "contains" match.

    % and _ are wildcards in LIKE, so if the user types them we escape them
    (with a backslash) to mean the plain characters.
    """
    for special in ("\\", "%", "_"):
        text = text.replace(special, "\\" + special)
    return f"%{text}%"


def search_recipes(query="", tags=(), db_path=DEFAULT_DB_PATH):
    """Recipes matching a search and/or tags, sorted by name (same shape as list_recipes).

    query: matches part of the recipe name OR any ingredient name, ignoring case.
           Blank means "don't filter by text".
    tags:  the recipe must have ALL of these tags. Empty means "don't filter by tag".
    """
    query = query.strip()
    tags = parse_tags(",".join(tags))  # lowercase, trimmed, no duplicates

    # Build the WHERE part piece by piece, only adding the filters that are in use.
    # The ? placeholders are filled from params, so user text is never pasted into the SQL.
    conditions = []
    params = []
    if query:
        # LIKE ignores upper/lower case (for plain A-Z letters) in SQLite.
        # EXISTS (...) is true if at least one ingredient of this recipe matches.
        conditions.append(
            "(recipes.name LIKE ? ESCAPE '\\'"
            " OR EXISTS (SELECT 1 FROM ingredients"
            "            WHERE ingredients.recipe_id = recipes.id"
            "            AND ingredients.name LIKE ? ESCAPE '\\'))"
        )
        pattern = _like_pattern(query)
        params += [pattern, pattern]
    if tags:
        # "Has all the tags": find recipes linked to any of the wanted tags, then
        # keep only those where the number of matching tags equals how many we asked for.
        placeholders = ", ".join("?" for _ in tags)
        conditions.append(
            "recipes.id IN (SELECT recipe_tags.recipe_id FROM recipe_tags"
            "               JOIN tags ON tags.id = recipe_tags.tag_id"
            f"              WHERE tags.name IN ({placeholders})"
            "               GROUP BY recipe_tags.recipe_id"
            "               HAVING COUNT(*) = ?)"
        )
        params += tags + [len(tags)]

    sql = "SELECT id, name, servings FROM recipes"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY name"

    conn = get_connection(db_path)
    try:
        recipes = []
        for row in conn.execute(sql, params):
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
