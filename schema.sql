-- Database tables for the recipe app.
-- "IF NOT EXISTS" means running this file again won't erase existing data.
-- Older databases are missing some newer columns; db.init_db adds them.

CREATE TABLE IF NOT EXISTS recipes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL,
    servings INTEGER NOT NULL DEFAULT 1,
    steps    TEXT    NOT NULL DEFAULT '',  -- one step per line
    meal_type TEXT   NOT NULL DEFAULT '',  -- main, side, breakfast, dessert or other
    -- 1 means you picked the label yourself, so the app never re-guesses it
    proteins_by_hand  INTEGER NOT NULL DEFAULT 0,
    meal_type_by_hand INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingredients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL DEFAULT 0,  -- keeps ingredients in order
    amount    TEXT    NOT NULL DEFAULT '', -- stored as text, e.g. '1/3' or '1 1/2'
    unit      TEXT    NOT NULL DEFAULT '', -- e.g. 'cup', 'g', or blank
    name      TEXT    NOT NULL             -- e.g. 'flour'
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

-- Links recipes to tags (a recipe can have many tags, a tag many recipes)
CREATE TABLE IF NOT EXISTS recipe_tags (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, tag_id)
);

-- A recipe's protein labels (a recipe can have more than one):
-- chicken, beef, pork, fish, vegetarian or eggs-other (see labels.py)
CREATE TABLE IF NOT EXISTS recipe_proteins (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    protein   TEXT    NOT NULL,
    PRIMARY KEY (recipe_id, protein)
);

-- This week's plan: the recipes you're cooking and for how many servings.
-- There's only ever one plan; "Clear plan" empties this table.
CREATE TABLE IF NOT EXISTS plan_items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- keeps the order you added them
    recipe_id INTEGER NOT NULL UNIQUE REFERENCES recipes(id) ON DELETE CASCADE,
    servings  INTEGER NOT NULL
);
