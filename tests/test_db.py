"""Tests for the database functions in db.py. Each test gets its own temp database."""

import pytest

import db


@pytest.fixture
def db_path(tmp_path):
    # A fresh, empty database in a temp folder, so we never touch the real recipes.db
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def make_recipe(db_path, **overrides):
    """Create a sample recipe; tests can override any field."""
    fields = {
        "name": "Pancakes",
        "servings": 2,
        "ingredients": [
            {"amount": "1 1/2", "unit": "cup", "name": "flour"},
            {"amount": "", "unit": "", "name": "salt"},
        ],
        "steps": "Mix.\nCook.",
        "tags": ["breakfast", "quick"],
    }
    fields.update(overrides)
    return db.create_recipe(db_path=db_path, **fields)


def count_rows(db_path, table):
    conn = db.get_connection(db_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return count


# --- parse_tags ---

def test_parse_tags_trims_lowercases_and_skips_blanks():
    assert db.parse_tags(" Dinner ,QUICK,, ,vegetarian ") == ["dinner", "quick", "vegetarian"]


def test_parse_tags_removes_duplicates():
    assert db.parse_tags("dinner, Dinner, DINNER , quick") == ["dinner", "quick"]


def test_parse_tags_empty_text():
    assert db.parse_tags("") == []
    assert db.parse_tags(" , , ") == []


# --- create / read ---

def test_create_and_get_recipe(db_path):
    recipe_id = make_recipe(db_path)

    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["name"] == "Pancakes"
    assert recipe["servings"] == 2
    assert recipe["steps"] == "Mix.\nCook."
    assert recipe["tags"] == ["breakfast", "quick"]
    assert recipe["ingredients"][0] == {"amount": "1 1/2", "unit": "cup", "name": "flour"}


def test_blank_amount_is_saved_as_empty_text(db_path):
    recipe_id = make_recipe(db_path)

    salt = db.get_recipe(recipe_id, db_path=db_path)["ingredients"][1]

    assert salt == {"amount": "", "unit": "", "name": "salt"}


def test_get_missing_recipe_returns_none(db_path):
    assert db.get_recipe(999, db_path=db_path) is None


def test_shared_tags_are_not_duplicated(db_path):
    make_recipe(db_path, tags=["dinner"])
    make_recipe(db_path, name="Soup", tags=["dinner"])

    assert count_rows(db_path, "tags") == 1


def test_list_recipes_sorted_by_name_with_tags(db_path):
    make_recipe(db_path, name="Waffles", tags=["breakfast"])
    make_recipe(db_path, name="Apple pie", tags=[])

    recipes = db.list_recipes(db_path=db_path)

    assert [r["name"] for r in recipes] == ["Apple pie", "Waffles"]
    assert recipes[1]["tags"] == ["breakfast"]


# --- update ---

def test_update_recipe_replaces_everything(db_path):
    recipe_id = make_recipe(db_path)

    db.update_recipe(
        recipe_id,
        name="Big pancakes",
        servings=6,
        ingredients=[{"amount": "3", "unit": "cup", "name": "flour"}],
        steps="Mix well.",
        tags=["brunch"],
        db_path=db_path,
    )
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["name"] == "Big pancakes"
    assert recipe["servings"] == 6
    assert recipe["steps"] == "Mix well."
    assert recipe["ingredients"] == [{"amount": "3", "unit": "cup", "name": "flour"}]
    assert recipe["tags"] == ["brunch"]


# --- delete ---

def test_delete_recipe(db_path):
    recipe_id = make_recipe(db_path)

    db.delete_recipe(recipe_id, db_path=db_path)

    assert db.get_recipe(recipe_id, db_path=db_path) is None


def test_delete_removes_ingredients_and_tag_links(db_path):
    keep_id = make_recipe(db_path, name="Keep me")
    delete_id = make_recipe(db_path, name="Delete me")

    db.delete_recipe(delete_id, db_path=db_path)

    # Only the kept recipe's 2 ingredients and 2 tag links should remain
    assert count_rows(db_path, "ingredients") == 2
    assert count_rows(db_path, "recipe_tags") == 2
    assert db.get_recipe(keep_id, db_path=db_path)["tags"] == ["breakfast", "quick"]


# --- seed import ---

def test_seed_import_runs_once(db_path):
    first = db.import_seed_data(db_path)
    second = db.import_seed_data(db_path)  # like starting the app a second time

    assert first == 4
    assert second == 0
    assert len(db.list_recipes(db_path=db_path)) == 4


def test_seed_import_skipped_when_recipes_exist(db_path):
    make_recipe(db_path)

    assert db.import_seed_data(db_path) == 0
    assert len(db.list_recipes(db_path=db_path)) == 1


def test_seed_import_steps_and_blank_amounts(db_path):
    db.import_seed_data(db_path)
    quiche = next(r for r in db.list_recipes(db_path=db_path) if r["name"].startswith("Ham"))
    recipe = db.get_recipe(quiche["id"], db_path=db_path)

    # Steps list was joined with newlines; the degree sign survived
    assert recipe["steps"].split("\n")[0] == "Preheat oven to 375°F and grease a 9-inch dish."
    assert len(recipe["steps"].split("\n")) == 7
    assert recipe["ingredients"][-1] == {"amount": "", "unit": "", "name": "salt and pepper"}
    assert recipe["tags"] == ["breakfast", "eggs", "oven"]
