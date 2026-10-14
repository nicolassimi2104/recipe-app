-- Database tables for the recipe app.
-- "IF NOT EXISTS" means running this file again won't erase existing data.

CREATE TABLE IF NOT EXISTS recipes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL,
    servings INTEGER NOT NULL DEFAULT 1,
    steps    TEXT    NOT NULL DEFAULT ''   -- one step per line
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
