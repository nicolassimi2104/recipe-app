"""Small helpers for talking to the SQLite database."""

import json
import sqlite3
from pathlib import Path

import labels

BASE_DIR = Path(__file__).parent
DEFAULT_DB_PATH = BASE_DIR / "recipes.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH = BASE_DIR / "recipes.json"
SIDES_PATH = BASE_DIR / "sides.json"   # the starter side dishes


def get_connection(db_path=DEFAULT_DB_PATH):
    """Open a connection to the database.

    Rows come back as sqlite3.Row, so you can use row["name"] instead of row[1].
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # SQLite ignores foreign keys (like ON DELETE CASCADE) unless this is on
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to the recipes table after the first version. A database made
# before then doesn't have them, and CREATE TABLE IF NOT EXISTS won't add them.
NEW_RECIPE_COLUMNS = {
    "meal_type": "TEXT NOT NULL DEFAULT ''",
    "proteins_by_hand": "INTEGER NOT NULL DEFAULT 0",
    "meal_type_by_hand": "INTEGER NOT NULL DEFAULT 0",
    "cuisine": "TEXT NOT NULL DEFAULT ''",
    "cuisine_by_hand": "INTEGER NOT NULL DEFAULT 0",
    "side_type": "TEXT NOT NULL DEFAULT ''",
    "fridge_days": "INTEGER",
    "image": "TEXT NOT NULL DEFAULT ''",
    "source_url": "TEXT NOT NULL DEFAULT ''",
    "favorite": "INTEGER NOT NULL DEFAULT 0",
}

# Bump this when an upgrade step is added below. SQLite keeps the number in
# the file itself ("PRAGMA user_version"), so each step only runs once.
DB_VERSION = 3


def init_db(db_path=DEFAULT_DB_PATH):
    """Create the tables if they don't exist yet, and upgrade an older database.

    Safe to run every startup: nothing is ever deleted.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
        with conn:
            for column, definition in NEW_RECIPE_COLUMNS.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE recipes ADD COLUMN {column} {definition}")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    if version < 2:
        # Label the recipes saved before labels (version 1) or cuisine and
        # side type (version 2) existed. Only blank labels are filled in.
        backfill_labels(db_path)
    if version < 3:
        # The protein guess used to miss "boneless, skinless chicken
        # breasts" (it stopped at the first comma), so guess again
        reguess_proteins(db_path)
    if version < DB_VERSION:
        conn = get_connection(db_path)
        try:
            conn.execute(f"PRAGMA user_version = {DB_VERSION}")
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


def seed_side_bank(db_path=DEFAULT_DB_PATH, json_path=SIDES_PATH):
    """Add the starter side dishes from sides.json, once ever.

    A side whose name you already have is skipped. After the first run it
    never runs again (the done_once table remembers), so a starter side
    you deleted stays deleted. Returns how many sides were added.
    """
    conn = get_connection(db_path)
    try:
        if conn.execute("SELECT 1 FROM done_once WHERE name = 'side-bank'").fetchone():
            return 0
        existing = {_name_key(row["name"]) for row in conn.execute("SELECT name FROM recipes")}
    finally:
        conn.close()

    with open(json_path, encoding="utf-8") as f:
        sides = json.load(f)

    added = 0
    for side in sides:
        if _name_key(side["name"]) in existing:
            continue
        create_recipe(
            name=side["name"],
            servings=side["servings"],
            ingredients=side["ingredients"],
            steps="\n".join(side["steps"]),
            tags=parse_tags(",".join(side["tags"])),
            meal_type="side",
            cuisine=side["cuisine"],
            side_type=side["side_type"],
            fridge_days=side.get("fridge_days"),
            db_path=db_path,
        )
        added += 1

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("INSERT OR IGNORE INTO done_once (name) VALUES ('side-bank')")
    finally:
        conn.close()
    return added


# "Garlic  Green Beans" and "garlic green beans" count as the same name
def _name_key(name):
    return " ".join(name.split()).casefold()


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
# Labels: protein and meal type (the guessing rules are in labels.py)
# ---------------------------------------------------------------------------

def _proteins_for(conn, recipe_id):
    """Protein labels for one recipe, in chip order."""
    rows = conn.execute("SELECT protein FROM recipe_proteins WHERE recipe_id = ?", (recipe_id,))
    return labels.clean_proteins({row["protein"] for row in rows})


def _save_labels(conn, recipe_id, name, ingredients, tags, proteins=(), meal_type="",
                 cuisine="", side_type=""):
    """Save a recipe's labels. Any left blank are guessed from the recipe.

    Labels you picked are marked "by hand"; guessed ones aren't, so they
    can be guessed again when the ingredients change. Side type is only
    kept for sides (other recipes get "").
    """
    proteins = labels.clean_proteins(proteins)
    meal_type = labels.clean_meal_type(meal_type)
    cuisine = labels.clean_cuisine(cuisine)
    guessed_proteins, guessed_meal_type = labels.guess_labels(
        name, ingredients, tags, meal_type or None
    )
    final_meal_type = meal_type or guessed_meal_type
    side_type = labels.clean_side_type(side_type)
    if final_meal_type != "side":
        side_type = ""
    elif not side_type:
        side_type = labels.guess_side_type(name, ingredients)
    conn.execute(
        "UPDATE recipes SET meal_type = ?, proteins_by_hand = ?, meal_type_by_hand = ?,"
        " cuisine = ?, cuisine_by_hand = ?, side_type = ? WHERE id = ?",
        (final_meal_type, int(bool(proteins)), int(bool(meal_type)),
         cuisine or labels.guess_cuisine(name, ingredients, tags), int(bool(cuisine)),
         side_type, recipe_id),
    )
    conn.execute("DELETE FROM recipe_proteins WHERE recipe_id = ?", (recipe_id,))
    for protein in proteins or guessed_proteins:
        conn.execute(
            "INSERT INTO recipe_proteins (recipe_id, protein) VALUES (?, ?)", (recipe_id, protein)
        )


def backfill_labels(db_path=DEFAULT_DB_PATH):
    """Guess labels for recipes that don't have any yet (saved before labels existed).

    Only blank labels are filled in. A label set by hand is never changed,
    and neither is one that's already there. Returns how many recipes changed.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, meal_type, proteins_by_hand, meal_type_by_hand, cuisine,"
            " cuisine_by_hand, side_type FROM recipes"
        ).fetchall()
    finally:
        conn.close()

    changed = 0
    for row in rows:
        recipe = get_recipe(row["id"], db_path=db_path)
        fill_meal_type = not row["meal_type"] and not row["meal_type_by_hand"]
        fill_proteins = not recipe["proteins"] and not row["proteins_by_hand"]
        fill_cuisine = not row["cuisine"] and not row["cuisine_by_hand"]

        guessed_proteins, guessed_meal_type = labels.guess_labels(
            recipe["name"], recipe["ingredients"], recipe["tags"], row["meal_type"] or None
        )
        meal_type = row["meal_type"] or guessed_meal_type
        fill_side_type = meal_type == "side" and not row["side_type"]
        if not (fill_meal_type or fill_proteins or fill_cuisine or fill_side_type):
            continue
        conn = get_connection(db_path)
        try:
            with conn:
                if fill_meal_type:
                    conn.execute("UPDATE recipes SET meal_type = ? WHERE id = ?",
                                 (guessed_meal_type, row["id"]))
                if fill_cuisine:
                    conn.execute("UPDATE recipes SET cuisine = ? WHERE id = ?",
                                 (labels.guess_cuisine(recipe["name"], recipe["ingredients"],
                                                       recipe["tags"]), row["id"]))
                if fill_side_type:
                    conn.execute("UPDATE recipes SET side_type = ? WHERE id = ?",
                                 (labels.guess_side_type(recipe["name"], recipe["ingredients"]),
                                  row["id"]))
                if fill_proteins:
                    for protein in guessed_proteins:
                        conn.execute("INSERT INTO recipe_proteins (recipe_id, protein)"
                                     " VALUES (?, ?)", (row["id"], protein))
        finally:
            conn.close()
        changed += 1
    return changed


def reguess_proteins(db_path=DEFAULT_DB_PATH):
    """Guess the proteins again for every recipe whose proteins weren't set by hand.

    Used when the guessing rules get better. Returns how many recipes changed.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, meal_type FROM recipes WHERE proteins_by_hand = 0"
        ).fetchall()
    finally:
        conn.close()

    changed = 0
    for row in rows:
        recipe = get_recipe(row["id"], db_path=db_path)
        guessed, _ = labels.guess_labels(
            recipe["name"], recipe["ingredients"], recipe["tags"], row["meal_type"] or None
        )
        if guessed == recipe["proteins"]:
            continue
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute("DELETE FROM recipe_proteins WHERE recipe_id = ?", (row["id"],))
                for protein in guessed:
                    conn.execute("INSERT INTO recipe_proteins (recipe_id, protein)"
                                 " VALUES (?, ?)", (row["id"], protein))
        finally:
            conn.close()
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# Recipes: create / read / update / delete
# ---------------------------------------------------------------------------

def create_recipe(name, servings, ingredients, steps, tags, proteins=(), meal_type="",
                  cuisine="", side_type="", fridge_days=None, image="", source_url="",
                  db_path=DEFAULT_DB_PATH):
    """Add a new recipe and return its id.

    ingredients: list of {"amount": "1/3", "unit": "cup", "name": "flour"}
    steps: one string, one step per line
    tags: list of tag names (already cleaned by parse_tags)
    proteins, meal_type, cuisine, side_type: labels picked by hand. Leave
        them blank (the default, and what imports do) and they're guessed.
    fridge_days: how many days it keeps in the fridge, or None if unknown
    image, source_url: picture link and original page, or "" (imports fill them in)
    """
    conn = get_connection(db_path)
    try:
        # "with conn" saves everything at the end, or nothing if an error happens
        with conn:
            cursor = conn.execute(
                "INSERT INTO recipes (name, servings, steps, fridge_days, image, source_url)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (name, servings, steps, fridge_days, image, source_url),
            )
            recipe_id = cursor.lastrowid
            _save_ingredients(conn, recipe_id, ingredients)
            _save_tags(conn, recipe_id, tags)
            _save_labels(conn, recipe_id, name, ingredients, tags, proteins, meal_type,
                         cuisine, side_type)
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
        recipe["proteins"] = _proteins_for(conn, recipe_id)
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
    Each recipe has id, name, servings, meal_type, cuisine, side_type,
    fridge_days, tags and proteins.
    The home page's protein chips filter this list further (see app.py).
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

    sql = ("SELECT id, name, servings, meal_type, cuisine, side_type, fridge_days,"
           " image, favorite FROM recipes")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY name"

    conn = get_connection(db_path)
    try:
        recipes = []
        for row in conn.execute(sql, params):
            recipe = dict(row)
            recipe["tags"] = _tags_for(conn, recipe["id"])
            recipe["proteins"] = _proteins_for(conn, recipe["id"])
            recipes.append(recipe)
        return recipes
    finally:
        conn.close()


def update_recipe(recipe_id, name, servings, ingredients, steps, tags, proteins=None,
                  meal_type=None, cuisine=None, side_type="", fridge_days=None,
                  image=None, source_url=None, db_path=DEFAULT_DB_PATH):
    """Replace a recipe's details, ingredients and tags with the new values.

    proteins, meal_type, cuisine:
        None (the default) means "you didn't change it": a label set by hand
            stays as it is, and a guessed one is guessed again from the new
            ingredients.
        A value means you picked it by hand. A blank value ([] or "") means
            "guess it for me" from now on.
    side_type: the value to save ("" means guess it). Only kept for sides.
    fridge_days: the new value, or None for "don't know".
    image, source_url: None keeps what is saved; a value (or "") replaces it.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            current = conn.execute(
                "SELECT meal_type, proteins_by_hand, meal_type_by_hand, cuisine, cuisine_by_hand"
                " FROM recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
            if proteins is None:
                proteins = _proteins_for(conn, recipe_id) if current["proteins_by_hand"] else []
            if meal_type is None:
                meal_type = current["meal_type"] if current["meal_type_by_hand"] else ""
            if cuisine is None:
                cuisine = current["cuisine"] if current["cuisine_by_hand"] else ""
            conn.execute(
                "UPDATE recipes SET name = ?, servings = ?, steps = ?, fridge_days = ? WHERE id = ?",
                (name, servings, steps, fridge_days, recipe_id),
            )
            if image is not None:
                conn.execute("UPDATE recipes SET image = ? WHERE id = ?", (image, recipe_id))
            if source_url is not None:
                conn.execute("UPDATE recipes SET source_url = ? WHERE id = ?", (source_url, recipe_id))
            # Simplest approach: wipe the old ingredients and tag links, then save the new ones
            conn.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
            conn.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
            _save_ingredients(conn, recipe_id, ingredients)
            _save_tags(conn, recipe_id, tags)
            _save_labels(conn, recipe_id, name, ingredients, tags, proteins, meal_type,
                         cuisine, side_type)
    finally:
        conn.close()


def set_favorite(recipe_id, favorite, db_path=DEFAULT_DB_PATH):
    """Star (True) or un-star (False) a recipe. Does nothing if it doesn't exist."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE recipes SET favorite = ? WHERE id = ?", (1 if favorite else 0, recipe_id))
    finally:
        conn.close()


def list_sides(db_path=DEFAULT_DB_PATH):
    """Every recipe with meal type "side" (same shape as list_recipes)."""
    return [r for r in list_recipes(db_path=db_path) if r["meal_type"] == "side"]


def delete_recipe(recipe_id, db_path=DEFAULT_DB_PATH):
    """Delete a recipe. ON DELETE CASCADE also removes its ingredients, tag
    and protein links, and takes it off this week's plan."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# This week's plan (one plan, saved in the plan_items table)
# ---------------------------------------------------------------------------

def plan_servings(db_path=DEFAULT_DB_PATH):
    """What's on the plan, as {recipe_id: servings}. Quick, for buttons and counts."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT recipe_id, servings FROM plan_items ORDER BY id")
        return {row["recipe_id"]: row["servings"] for row in rows}
    finally:
        conn.close()


def get_plan(db_path=DEFAULT_DB_PATH):
    """The plan as (recipe, servings) pairs in the order you added them.

    recipe is the full dict from get_recipe, so this is exactly what
    grocery.merge_ingredients needs.
    """
    return [
        (get_recipe(recipe_id, db_path=db_path), servings)
        for recipe_id, servings in plan_servings(db_path=db_path).items()
    ]


def add_to_plan(recipe_id, servings=None, db_path=DEFAULT_DB_PATH):
    """Put a recipe on the plan (servings defaults to the recipe's own).

    Already on it: nothing changes. Returns False if the recipe doesn't exist.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT servings FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return False
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO plan_items (recipe_id, servings) VALUES (?, ?)",
                (recipe_id, servings or row["servings"]),
            )
        return True
    finally:
        conn.close()


def remove_from_plan(recipe_id, db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM plan_items WHERE recipe_id = ?", (recipe_id,))
    finally:
        conn.close()


def set_plan_servings(recipe_id, servings, db_path=DEFAULT_DB_PATH):
    """Change the servings of a recipe that's on the plan (does nothing if it isn't)."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE plan_items SET servings = ? WHERE recipe_id = ?",
                         (servings, recipe_id))
    finally:
        conn.close()


def clear_plan(db_path=DEFAULT_DB_PATH):
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM plan_items")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fresh finds: suggestions from recipe-site feeds (the reading is in suggestions.py)
# ---------------------------------------------------------------------------

SUGGESTION_STATUSES = ("new", "imported", "dismissed")


def add_suggestions(suggestions, fetched_at, db_path=DEFAULT_DB_PATH):
    """Save new suggestions ({"title", "url", "source", "image"}) in the order given.

    A link that's already saved (new, imported or dismissed) is skipped.
    Returns how many were added.
    """
    conn = get_connection(db_path)
    try:
        added = 0
        with conn:
            for s in suggestions:
                # INSERT OR IGNORE: url is UNIQUE, so a link we already have is skipped
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO suggestions (title, url, source, image, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (s["title"], s["url"], s.get("source", ""), s.get("image", ""), fetched_at),
                )
                added += cursor.rowcount
        return added
    finally:
        conn.close()


def newest_suggestion_time(db_path=DEFAULT_DB_PATH):
    """When the newest suggestion was found (text like "2026-10-18T09:30:00"), or None."""
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT MAX(fetched_at) FROM suggestions").fetchone()[0]
    finally:
        conn.close()


def new_suggestions(limit=3, db_path=DEFAULT_DB_PATH):
    """The newest suggestions not yet imported or dismissed, as dicts."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM suggestions WHERE status = 'new'"
            " ORDER BY fetched_at DESC, id LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_suggestion(suggestion_id, db_path=DEFAULT_DB_PATH):
    """One suggestion as a dict, or None if not found."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_suggestion_status(suggestion_id, status, recipe_id=None, db_path=DEFAULT_DB_PATH):
    """Mark a suggestion "new", "imported" (with the recipe it became) or "dismissed"."""
    if status not in SUGGESTION_STATUSES:
        raise ValueError(f"Unknown suggestion status: {status!r}")
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE suggestions SET status = ?, recipe_id = ? WHERE id = ?",
                         (status, recipe_id, suggestion_id))
    finally:
        conn.close()
