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


# --- search_recipes / list_tags ---

@pytest.fixture
def search_db(db_path):
    """Three recipes with different names, ingredients and tags to search through."""
    make_recipe(db_path, name="Chicken Curry", tags=["dinner", "spicy"],
                ingredients=[{"amount": "1", "unit": "lb", "name": "chicken thighs"}])
    make_recipe(db_path, name="Fried Rice", tags=["dinner", "quick"],
                ingredients=[{"amount": "2", "unit": "cup", "name": "rice"},
                             {"amount": "1", "unit": "cup", "name": "Diced Chicken"}])
    make_recipe(db_path, name="Pancakes", tags=["breakfast", "quick"],
                ingredients=[{"amount": "1", "unit": "cup", "name": "flour"}])
    return db_path


def names(recipes):
    return [r["name"] for r in recipes]


def test_search_with_no_filters_returns_everything(search_db):
    assert names(db.search_recipes(db_path=search_db)) == ["Chicken Curry", "Fried Rice", "Pancakes"]


def test_search_matches_part_of_name_ignoring_case(search_db):
    assert names(db.search_recipes("PANCAKE", db_path=search_db)) == ["Pancakes"]
    assert names(db.search_recipes("  curr ", db_path=search_db)) == ["Chicken Curry"]


def test_search_matches_ingredient_name(search_db):
    # "chick" is in Chicken Curry's name and in Fried Rice's "Diced Chicken" ingredient
    assert names(db.search_recipes("chick", db_path=search_db)) == ["Chicken Curry", "Fried Rice"]
    assert names(db.search_recipes("flour", db_path=search_db)) == ["Pancakes"]


def test_search_lists_a_recipe_once_even_if_several_ingredients_match(search_db):
    make_recipe(db_path=search_db, name="Egg Salad", tags=[],
                ingredients=[{"name": "eggs"}, {"name": "egg yolk mayo"}])
    assert names(db.search_recipes("egg", db_path=search_db)) == ["Egg Salad"]


def test_search_treats_percent_and_underscore_as_plain_text(search_db):
    # In SQL LIKE these are wildcards; a search for "%" shouldn't match everything
    assert db.search_recipes("%", db_path=search_db) == []
    assert db.search_recipes("_", db_path=search_db) == []


def test_single_tag_filter(search_db):
    assert names(db.search_recipes(tags=["quick"], db_path=search_db)) == ["Fried Rice", "Pancakes"]


def test_several_tags_must_all_match(search_db):
    assert names(db.search_recipes(tags=["dinner", "quick"], db_path=search_db)) == ["Fried Rice"]
    # Upper case and repeats are cleaned up the same way as the recipe form
    assert names(db.search_recipes(tags=["Quick", "dinner", "quick"], db_path=search_db)) == ["Fried Rice"]


def test_search_and_tags_together(search_db):
    assert names(db.search_recipes("chicken", ["spicy"], db_path=search_db)) == ["Chicken Curry"]
    assert names(db.search_recipes("chicken", ["quick"], db_path=search_db)) == ["Fried Rice"]


def test_no_results(search_db):
    assert db.search_recipes("tofu", db_path=search_db) == []
    assert db.search_recipes(tags=["breakfast", "dinner"], db_path=search_db) == []
    assert db.search_recipes(tags=["no-such-tag"], db_path=search_db) == []


def test_search_results_include_tags(search_db):
    curry = db.search_recipes("curry", db_path=search_db)[0]
    assert curry["tags"] == ["dinner", "spicy"]


def test_list_tags_only_used_tags_alphabetical(search_db):
    curry_id = db.search_recipes("curry", db_path=search_db)[0]["id"]
    db.delete_recipe(curry_id, db_path=search_db)  # "spicy" is now unused

    assert db.list_tags(db_path=search_db) == ["breakfast", "dinner", "quick"]
    assert db.count_recipes(db_path=search_db) == 2


# --- Labels: guessed on save, kept when set by hand ---

CHICKEN = [{"amount": "1", "unit": "lb", "name": "chicken thighs"},
           {"amount": "1", "unit": "cup", "name": "chicken broth"}]
BEEF = [{"amount": "1", "unit": "lb", "name": "ground beef"}]


def test_new_recipe_gets_guessed_labels(db_path):
    recipe_id = make_recipe(db_path, name="Chicken Dinner", ingredients=CHICKEN, tags=["dinner"])
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["proteins"] == ["chicken"]
    assert recipe["meal_type"] == "main"
    assert recipe["proteins_by_hand"] == 0


def test_labels_picked_when_creating_are_kept(db_path):
    recipe_id = make_recipe(db_path, ingredients=CHICKEN, proteins=["beef"], meal_type="side")
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["proteins"] == ["beef"]
    assert recipe["meal_type"] == "side"
    assert recipe["proteins_by_hand"] == 1
    assert recipe["meal_type_by_hand"] == 1


def test_editing_ingredients_re_guesses_guessed_labels(db_path):
    recipe_id = make_recipe(db_path, ingredients=CHICKEN, tags=[])
    db.update_recipe(recipe_id, "Burgers", 2, BEEF, "", [], db_path=db_path)

    assert db.get_recipe(recipe_id, db_path=db_path)["proteins"] == ["beef"]


def test_editing_ingredients_keeps_hand_picked_labels(db_path):
    recipe_id = make_recipe(db_path, ingredients=CHICKEN, tags=[], proteins=["pork"], meal_type="side")
    db.update_recipe(recipe_id, "Burgers", 2, BEEF, "", [], db_path=db_path)
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["proteins"] == ["pork"]
    assert recipe["meal_type"] == "side"


def test_blank_labels_on_edit_mean_guess_again(db_path):
    recipe_id = make_recipe(db_path, ingredients=BEEF, tags=[], proteins=["pork"], meal_type="side")
    db.update_recipe(recipe_id, "Burgers", 2, BEEF, "", [], proteins=[], meal_type="", db_path=db_path)
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["proteins"] == ["beef"]
    assert recipe["meal_type"] == "main"
    assert recipe["proteins_by_hand"] == 0


def test_search_results_include_labels(db_path):
    make_recipe(db_path, name="Burgers", ingredients=BEEF, tags=[])
    (recipe,) = db.search_recipes(db_path=db_path)
    assert recipe["proteins"] == ["beef"]
    assert recipe["meal_type"] == "main"


# --- Upgrading an older database and the one-time backfill ---

OLD_SCHEMA = """
CREATE TABLE recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                      servings INTEGER NOT NULL DEFAULT 1, steps TEXT NOT NULL DEFAULT '');
CREATE TABLE ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL,
                          position INTEGER NOT NULL DEFAULT 0, amount TEXT NOT NULL DEFAULT '',
                          unit TEXT NOT NULL DEFAULT '', name TEXT NOT NULL);
CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE recipe_tags (recipe_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
                          PRIMARY KEY (recipe_id, tag_id));
INSERT INTO recipes (name, servings, steps) VALUES ('Old Chicken Dish', 4, 'Cook.');
INSERT INTO ingredients (recipe_id, amount, unit, name) VALUES (1, '2', 'lb', 'chicken thighs');
INSERT INTO tags (name) VALUES ('dessert');
"""


def test_old_database_is_upgraded_and_labelled(tmp_path):
    path = tmp_path / "old.db"
    conn = db.get_connection(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    db.init_db(path)
    recipe = db.get_recipe(1, db_path=path)

    assert recipe["name"] == "Old Chicken Dish"     # nothing lost
    assert recipe["ingredients"][0]["name"] == "chicken thighs"
    assert recipe["proteins"] == ["chicken"]
    assert recipe["meal_type"] == "main"
    assert db.plan_servings(db_path=path) == {}     # the plan table exists too
    db.init_db(path)                                # running it again is fine


def test_backfill_fills_blanks_but_never_overwrites_hand_set_labels(db_path):
    by_hand = make_recipe(db_path, name="Chicken Thing", ingredients=CHICKEN, tags=[],
                          proteins=["fish"], meal_type="dessert")
    guessed = make_recipe(db_path, name="Burgers", ingredients=BEEF, tags=[])
    # Pretend both were saved before labels existed: wipe the guessed one's
    # labels, and the hand-set one's proteins (an odd state, but it must survive)
    conn = db.get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM recipe_proteins WHERE recipe_id = ?", (guessed,))
        conn.execute("UPDATE recipes SET meal_type = '' WHERE id = ?", (guessed,))
    conn.close()

    assert db.backfill_labels(db_path) == 1

    assert db.get_recipe(guessed, db_path=db_path)["proteins"] == ["beef"]
    assert db.get_recipe(guessed, db_path=db_path)["meal_type"] == "main"
    hand = db.get_recipe(by_hand, db_path=db_path)
    assert hand["proteins"] == ["fish"]
    assert hand["meal_type"] == "dessert"
    assert db.backfill_labels(db_path) == 0         # nothing left to fill


def test_backfill_only_runs_once_per_database(db_path):
    recipe_id = make_recipe(db_path, ingredients=BEEF, tags=[])
    conn = db.get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM recipe_proteins")
    conn.close()

    db.init_db(db_path)   # already at the current version: no backfill

    assert db.get_recipe(recipe_id, db_path=db_path)["proteins"] == []


def test_reguess_fixes_old_guesses_but_not_hand_set_ones(db_path):
    chicken = [{"amount": "1 1/2", "unit": "lb", "name": "boneless, skinless chicken breasts"}]
    guessed = make_recipe(db_path, name="Marry Me Chicken", ingredients=chicken, tags=[])
    by_hand = make_recipe(db_path, name="Odd One", ingredients=chicken, tags=[],
                          proteins=["fish"])
    # Pretend the guessed one was saved by the old rules, which said vegetarian
    conn = db.get_connection(db_path)
    with conn:
        conn.execute("UPDATE recipe_proteins SET protein = 'vegetarian' WHERE recipe_id = ?",
                     (guessed,))
    conn.close()

    assert db.reguess_proteins(db_path) == 1
    assert db.get_recipe(guessed, db_path=db_path)["proteins"] == ["chicken"]
    assert db.get_recipe(by_hand, db_path=db_path)["proteins"] == ["fish"]
    assert db.reguess_proteins(db_path) == 0        # nothing left to fix


def test_upgrading_from_version_2_reguesses_proteins(db_path):
    chicken = [{"amount": "1 1/2", "unit": "lb", "name": "boneless, skinless chicken breasts"}]
    recipe_id = make_recipe(db_path, name="Marry Me Chicken", ingredients=chicken, tags=[])
    conn = db.get_connection(db_path)
    with conn:
        conn.execute("UPDATE recipe_proteins SET protein = 'vegetarian'")
    conn.execute("PRAGMA user_version = 2")
    conn.close()

    db.init_db(db_path)

    assert db.get_recipe(recipe_id, db_path=db_path)["proteins"] == ["chicken"]


# --- This week's plan ---

def test_add_and_remove_from_plan(db_path):
    first = make_recipe(db_path, servings=4)
    second = make_recipe(db_path, name="Waffles", servings=2)

    assert db.add_to_plan(second, db_path=db_path)
    assert db.add_to_plan(first, servings=8, db_path=db_path)
    assert db.plan_servings(db_path=db_path) == {second: 2, first: 8}   # order added

    db.remove_from_plan(second, db_path=db_path)
    assert db.plan_servings(db_path=db_path) == {first: 8}


def test_adding_twice_keeps_one_entry_and_its_servings(db_path):
    recipe_id = make_recipe(db_path, servings=4)
    db.add_to_plan(recipe_id, servings=6, db_path=db_path)
    db.add_to_plan(recipe_id, db_path=db_path)

    assert db.plan_servings(db_path=db_path) == {recipe_id: 6}


def test_adding_a_missing_recipe_does_nothing(db_path):
    assert db.add_to_plan(999, db_path=db_path) is False
    assert db.plan_servings(db_path=db_path) == {}


def test_plan_servings_can_change_and_plan_can_be_cleared(db_path):
    recipe_id = make_recipe(db_path)
    db.add_to_plan(recipe_id, db_path=db_path)
    db.set_plan_servings(recipe_id, 10, db_path=db_path)

    ((recipe, servings),) = db.get_plan(db_path=db_path)
    assert recipe["name"] == "Pancakes"
    assert servings == 10

    db.clear_plan(db_path=db_path)
    assert db.get_plan(db_path=db_path) == []


def test_deleting_a_recipe_takes_it_off_the_plan(db_path):
    recipe_id = make_recipe(db_path)
    db.add_to_plan(recipe_id, db_path=db_path)
    db.delete_recipe(recipe_id, db_path=db_path)

    assert db.plan_servings(db_path=db_path) == {}
