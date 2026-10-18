"""Tests for side dish pairing: cuisine and side type guessing, the pairing
rules, the starter side bank, and the "Sides that fit" section."""

import json
import re
import sqlite3

import pytest

import app as app_module
import db
import labels
import pairing
from app import create_app


def ing(name, amount="1", unit="cup"):
    return {"amount": amount, "unit": unit, "name": name}


# --- Guessing cuisine ---

@pytest.mark.parametrize("name, ingredients, tags, expected", [
    ("Chicken Tacos", [ing("chicken")], [], "mexican"),
    ("Weeknight Spaghetti", [ing("ground beef")], [], "italian"),
    ("Beef and Broccoli", [ing("soy sauce", "2", "tbsp"), ing("ginger", "1", "tbsp")], [], "asian"),
    ("Sheet Pan Chicken", [ing("feta"), ing("chickpeas")], [], "mediterranean"),
    ("Meatloaf", [ing("ground beef")], [], "american"),
    ("Dinner Bowl", [ing("rice")], ["mexican"], "mexican"),        # tags count like the name
])
def test_guess_cuisine(name, ingredients, tags, expected):
    assert labels.guess_cuisine(name, ingredients, tags) == expected


def test_one_ingredient_hint_is_not_enough():
    # Lots of dishes have a splash of soy sauce; it takes a second hint
    assert labels.guess_cuisine("Pan Chicken", [ing("soy sauce", "1", "tbsp")]) == "other"


def test_no_hints_means_other():
    assert labels.guess_cuisine("Chicken Stroganoff", [ing("chicken"), ing("sour cream")]) == "other"


def test_greek_yogurt_is_not_mediterranean():
    assert labels.guess_cuisine("Greek Yogurt Parfait", [ing("greek yogurt")]) == "other"


# --- What a dish already has, and guessing side type ---

def test_plate_parts_finds_starch_and_veg():
    assert labels.plate_parts([ing("potatoes", "2", "lb"), ing("broccoli florets")]) == (True, True)
    assert labels.plate_parts([ing("chicken thighs", "2", "lb")]) == (False, False)


def test_flavourings_and_garnishes_dont_count():
    ingredients = [
        ing("rice vinegar", "2", "tbsp"),       # not rice
        ing("bread crumbs", "1/2", "cup"),      # not bread
        ing("tomato paste", "2", "tbsp"),       # not a vegetable
        ing("celery, minced", "1", "tbsp"),     # too little to count
        ing("mushrooms", "8", "oz"),            # flavour, not "the veg"
        ing("onion", "1", ""),
    ]
    assert labels.plate_parts(ingredients) == (False, False)


def test_corn_tortillas_are_a_starch_not_a_vegetable():
    assert labels.plate_parts([ing("corn tortillas", "8", "")]) == (True, False)


@pytest.mark.parametrize("name, ingredients, expected", [
    ("Kale Caesar Salad", [ing("kale")], "salad"),
    ("Creamy Coleslaw", [ing("cabbage")], "salad"),
    ("Garlic Mashed Potatoes", [ing("potatoes", "2", "lb")], "starch"),
    ("Roasted Brussels Sprouts", [ing("brussels sprouts", "1", "lb")], "vegetable"),
    ("Mom's Favourite", [ing("long-grain rice")], "starch"),     # from the ingredients
    ("Something Nice", [ing("frozen peas", "2", "cup")], "vegetable"),
    ("Applesauce", [ing("apples", "4", "")], "other"),
])
def test_guess_side_type(name, ingredients, expected):
    assert labels.guess_side_type(name, ingredients) == expected


# --- Pairing rules ---

def side(side_id, side_type, cuisine="other"):
    return {"id": side_id, "name": f"Side {side_id}", "side_type": side_type, "cuisine": cuisine}


def main(ingredients, cuisine="other", main_id=100):
    return {"id": main_id, "name": "Main", "ingredients": ingredients, "cuisine": cuisine}


MEAT_ONLY = [ing("chicken thighs", "2", "lb")]
MEAT_AND_STARCH = [ing("chicken thighs", "2", "lb"), ing("potatoes", "2", "lb")]
MEAT_AND_VEG = [ing("chicken thighs", "2", "lb"), ing("broccoli florets", "3", "cup")]
EVERYTHING = MEAT_AND_STARCH + [ing("green beans", "1", "lb")]


def test_main_with_no_veg_wants_veg_or_salad():
    assert pairing.wanted_side_types(main(MEAT_ONLY)) == ({"vegetable", "salad"}, "no-veg")


def test_starch_main_is_balanced_by_a_veg():
    assert pairing.wanted_side_types(main(MEAT_AND_STARCH)) == ({"vegetable", "salad"}, "no-veg")


def test_main_with_veg_but_no_starch_wants_a_starch():
    assert pairing.wanted_side_types(main(MEAT_AND_VEG)) == ({"starch"}, "no-starch")


def test_main_with_everything_takes_any_side():
    assert pairing.wanted_side_types(main(EVERYTHING)) == (set(), "both")


def test_veg_and_salads_come_first_for_a_starchy_main():
    sides = [side(1, "starch"), side(2, "starch"), side(3, "vegetable"),
             side(4, "other"), side(5, "salad"), side(6, "starch")]

    picked = pairing.pick_sides(main(MEAT_AND_STARCH), sides)

    assert {s["side_type"] for s in picked[:2]} <= {"vegetable", "salad"}
    assert {s["id"] for s in picked[:2]} == {3, 5}


def test_starch_comes_first_for_a_main_with_veg():
    sides = [side(1, "vegetable"), side(2, "salad"), side(3, "starch"), side(4, "vegetable")]

    assert pairing.pick_sides(main(MEAT_AND_VEG), sides)[0]["id"] == 3


def test_matching_cuisine_wins_among_the_right_type():
    sides = [side(i, "vegetable", "american") for i in range(1, 6)]
    sides.append(side(9, "vegetable", "asian"))

    picked = pairing.pick_sides(main(MEAT_ONLY, cuisine="asian"), sides)

    assert picked[0]["id"] == 9


def test_right_type_beats_matching_cuisine():
    sides = [side(1, "starch", "italian"), side(2, "vegetable", "american")]

    picked = pairing.pick_sides(main(MEAT_ONLY, cuisine="italian"), sides)

    assert [s["id"] for s in picked] == [2, 1]


def test_cuisine_match_beats_nothing_in_common():
    sides = [side(1, "starch", "american"), side(2, "starch", "italian"),
             side(3, "starch", "asian"), side(4, "starch", "mexican")]

    picked = pairing.pick_sides(main(MEAT_ONLY, cuisine="italian"), sides)

    assert picked[0]["id"] == 2


def test_other_cuisine_is_not_a_match():
    assert pairing.score(side(1, "starch", "other"), set(), "other") == 0


def test_falls_back_to_anything_when_nothing_fits():
    # A main with no veg, but there are only starches: still show 3
    sides = [side(i, "starch", "american") for i in range(1, 6)]

    picked = pairing.pick_sides(main(MEAT_ONLY, cuisine="asian"), sides)

    assert len(picked) == 3


def test_fewer_sides_than_three_shows_what_there_is():
    assert len(pairing.pick_sides(main(MEAT_ONLY), [side(1, "salad")])) == 1
    assert pairing.pick_sides(main(MEAT_ONLY), []) == []


def test_a_recipe_is_never_its_own_side():
    sides = [side(100, "vegetable"), side(2, "vegetable")]
    assert [s["id"] for s in pairing.pick_sides(main(MEAT_ONLY, main_id=100), sides)] == [2]


def test_same_main_gets_the_same_picks_every_time():
    sides = [side(i, "vegetable") for i in range(1, 11)]
    first = pairing.pick_sides(main(MEAT_ONLY), sides)
    assert pairing.pick_sides(main(MEAT_ONLY), sides) == first


def test_shuffle_gives_a_different_set_when_there_are_enough_sides():
    sides = [side(i, t) for i, t in enumerate(["vegetable", "salad", "starch", "other"] * 3, 1)]
    the_main = main(MEAT_ONLY)

    sets = [{s["id"] for s in pairing.pick_sides(the_main, sides, shuffle=n)} for n in range(4)]

    for n in range(3):
        assert sets[n] != sets[n + 1]
    # The first 4 shuffles show all 12 sides, none twice
    assert set().union(*sets) == {s["id"] for s in sides}


def test_shuffle_with_a_few_more_sides_than_three_still_changes():
    sides = [side(i, "vegetable") for i in range(1, 5)]     # 4 sides
    the_main = main(MEAT_ONLY)
    first = pairing.pick_sides(the_main, sides, shuffle=0)
    second = pairing.pick_sides(the_main, sides, shuffle=1)
    assert first != second
    assert len(second) == 3


def test_shuffle_with_three_or_fewer_sides_shows_the_same():
    sides = [side(1, "vegetable"), side(2, "salad"), side(3, "starch")]
    the_main = main(MEAT_ONLY)
    assert pairing.pick_sides(the_main, sides, 1) == pairing.pick_sides(the_main, sides, 0)


# --- Saving the new fields ---

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_side_fields_are_saved(db_path):
    recipe_id = db.create_recipe("Rice", 4, [ing("rice")], "Cook.", [], meal_type="side",
                                 cuisine="asian", side_type="starch", fridge_days=4,
                                 db_path=db_path)
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert (recipe["side_type"], recipe["cuisine"], recipe["fridge_days"]) == ("starch", "asian", 4)
    assert recipe["cuisine_by_hand"] == 1


def test_blank_side_fields_are_guessed(db_path):
    recipe_id = db.create_recipe("Kale Salad", 4, [ing("kale")], "Toss.", ["side"],
                                 db_path=db_path)
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["meal_type"] == "side"
    assert recipe["side_type"] == "salad"
    assert recipe["fridge_days"] is None
    assert recipe["cuisine_by_hand"] == 0


def test_mains_have_no_side_type(db_path):
    recipe_id = db.create_recipe("Chicken Tacos", 4, [ing("chicken")], "Cook.", [],
                                 side_type="salad", db_path=db_path)
    recipe = db.get_recipe(recipe_id, db_path=db_path)

    assert recipe["side_type"] == ""
    assert recipe["cuisine"] == "mexican"


def test_cuisine_set_by_hand_survives_an_edit(db_path):
    recipe_id = db.create_recipe("Chicken Tacos", 4, [ing("chicken")], "Cook.", [],
                                 cuisine="american", db_path=db_path)
    db.update_recipe(recipe_id, "Chicken Tacos", 4, [ing("chicken"), ing("salsa")], "Cook.", [],
                     db_path=db_path)

    assert db.get_recipe(recipe_id, db_path=db_path)["cuisine"] == "american"


def test_guessed_cuisine_is_guessed_again_after_an_edit(db_path):
    recipe_id = db.create_recipe("Dinner", 4, [ing("chicken")], "Cook.", [], db_path=db_path)
    db.update_recipe(recipe_id, "Dinner Tacos", 4, [ing("chicken")], "Cook.", [], db_path=db_path)

    assert db.get_recipe(recipe_id, db_path=db_path)["cuisine"] == "mexican"


def test_list_sides_only_lists_sides(db_path):
    db.create_recipe("Kale Salad", 4, [ing("kale")], "Toss.", [], meal_type="side", db_path=db_path)
    db.create_recipe("Chicken Tacos", 4, [ing("chicken")], "Cook.", [], db_path=db_path)

    assert [r["name"] for r in db.list_sides(db_path=db_path)] == ["Kale Salad"]


# A database from V3 item A/B: labels, but no cuisine/side columns yet
V1_SCHEMA = """
CREATE TABLE recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                      servings INTEGER NOT NULL DEFAULT 1, steps TEXT NOT NULL DEFAULT '',
                      meal_type TEXT NOT NULL DEFAULT '',
                      proteins_by_hand INTEGER NOT NULL DEFAULT 0,
                      meal_type_by_hand INTEGER NOT NULL DEFAULT 0);
CREATE TABLE ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL,
                          position INTEGER NOT NULL DEFAULT 0, amount TEXT NOT NULL DEFAULT '',
                          unit TEXT NOT NULL DEFAULT '', name TEXT NOT NULL);
CREATE TABLE recipe_proteins (recipe_id INTEGER NOT NULL, protein TEXT NOT NULL,
                              PRIMARY KEY (recipe_id, protein));
INSERT INTO recipes (name, servings, steps, meal_type) VALUES ('Beef Tacos', 4, 'Cook.', 'main');
INSERT INTO recipes (name, servings, steps, meal_type, meal_type_by_hand)
    VALUES ('Garlic Mashed Potatoes', 4, 'Mash.', 'side', 1);
INSERT INTO ingredients (recipe_id, amount, unit, name) VALUES (1, '1', 'lb', 'ground beef');
INSERT INTO ingredients (recipe_id, amount, unit, name) VALUES (2, '2', 'lb', 'potatoes');
INSERT INTO recipe_proteins VALUES (1, 'beef'), (2, 'vegetarian');
PRAGMA user_version = 1;
"""


def test_older_database_gets_cuisine_and_side_type(tmp_path):
    path = tmp_path / "v1.db"
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.close()

    db.init_db(path)

    tacos = db.get_recipe(1, db_path=path)
    potatoes = db.get_recipe(2, db_path=path)
    assert tacos["cuisine"] == "mexican"
    assert tacos["proteins"] == ["beef"]           # nothing lost
    assert potatoes["side_type"] == "starch"
    assert potatoes["meal_type"] == "side"
    assert potatoes["fridge_days"] is None


# --- The starter side bank ---

SIDES_IN_BANK = len(json.load(open(db.SIDES_PATH, encoding="utf-8")))


def test_side_bank_is_varied():
    bank = json.load(open(db.SIDES_PATH, encoding="utf-8"))
    assert 14 <= len(bank) <= 18
    assert {s["side_type"] for s in bank} == set(labels.SIDE_TYPES)
    assert {s["cuisine"] for s in bank} == set(labels.CUISINES) - {"other"}
    # Several keep 4-5 days and are good for meal prep
    assert sum(1 for s in bank if s["fridge_days"] >= 4 and "reheats-well" in s["tags"]) >= 5
    assert len({s["name"] for s in bank}) == len(bank)


def test_side_bank_is_seeded_only_once(db_path):
    assert db.seed_side_bank(db_path) == SIDES_IN_BANK
    assert db.seed_side_bank(db_path) == 0       # like starting the app again

    sides = db.list_sides(db_path=db_path)
    assert len(sides) == SIDES_IN_BANK
    rice = next(s for s in sides if s["name"] == "Cilantro Lime Rice")
    assert (rice["side_type"], rice["cuisine"], rice["fridge_days"]) == ("starch", "mexican", 4)


def test_side_bank_skips_sides_you_already_have(db_path):
    db.create_recipe("cilantro lime  rice", 2, [ing("rice")], "My way.", [], db_path=db_path)

    assert db.seed_side_bank(db_path) == SIDES_IN_BANK - 1
    assert db.count_recipes(db_path=db_path) == SIDES_IN_BANK


def test_deleted_starter_sides_stay_deleted(db_path):
    db.seed_side_bank(db_path)
    for s in db.list_sides(db_path=db_path):
        db.delete_recipe(s["id"], db_path=db_path)

    assert db.seed_side_bank(db_path) == 0
    assert db.list_sides(db_path=db_path) == []


# --- The pages ---

@pytest.fixture
def with_sides(monkeypatch):
    monkeypatch.setattr(app_module, "ADD_STARTER_SIDES", True)


@pytest.fixture
def client(tmp_path, with_sides):
    return create_app(db_path=tmp_path / "app.db").test_client()


@pytest.fixture
def app_db(tmp_path):
    return tmp_path / "app.db"


def page(client, url):
    return client.get(url).get_data(as_text=True)


def side_cards(html):
    """Names of the suggested sides on a recipe page."""
    section = html.split('id="sides"')[1].split("</section>")[0]
    return re.findall(r'class="side-name">([^<]+)</a>', section)


def test_app_start_seeds_starter_sides_once(tmp_path, with_sides):
    path = tmp_path / "app.db"
    create_app(db_path=path)
    create_app(db_path=path)      # restart

    assert db.count_recipes(db_path=path) == 4 + SIDES_IN_BANK


def test_main_page_shows_three_sides(client):
    # Recipe 2, Mushroom Butter Sauce Chicken & Potatoes, has potatoes but no veg
    html = page(client, "/recipes/2")

    assert "Sides that fit" in html
    assert "no vegetables" in html
    names = side_cards(html)
    assert len(names) == 3
    sides = {s["name"]: s for s in db.list_sides(db_path=client.application.config["DB_PATH"])}
    assert all(sides[n]["side_type"] in ("vegetable", "salad") for n in names)
    assert html.count("Keeps ") >= 3          # fridge days shown on each


def test_shuffle_button_shows_a_different_set(client):
    html = page(client, "/recipes/2")
    assert 'href="/recipes/2?shuffle=1#sides"' in html

    first = side_cards(html)
    second = side_cards(page(client, "/recipes/2?shuffle=1"))
    assert set(first) != set(second)
    assert page(client, "/recipes/2") == html    # no shuffle: same as before


def test_shuffle_keeps_scaling_and_units(client):
    html = page(client, "/recipes/2?servings=8&units=metric")
    assert "/recipes/2?servings=8&amp;units=metric&amp;shuffle=1#sides" in html


def test_bad_shuffle_value_is_ignored(client):
    assert client.get("/recipes/2?shuffle=abc").status_code == 200
    assert client.get("/recipes/2?shuffle=-3").status_code == 200


def test_side_and_breakfast_pages_have_no_suggestions(client):
    assert "Sides that fit" not in page(client, "/recipes/5")     # a side
    assert "Sides that fit" not in page(client, "/recipes/1")     # the quiche (breakfast)


def test_main_with_no_sides_yet(tmp_path):
    client = create_app(db_path=tmp_path / "plain.db").test_client()   # starter sides off
    html = page(client, "/recipes/2")
    assert "No side dishes yet" in html
    assert "Shuffle" not in html


def test_side_page_shows_its_details(client):
    html = page(client, "/recipes/5")     # first starter side: Cilantro Lime Rice
    assert "Cilantro Lime Rice" in html
    assert "Keeps 4 days in the fridge" in html
    assert '<span class="label meal">starch</span>' in html
    assert '<span class="label cuisine">mexican</span>' in html


def test_side_added_from_a_main_reaches_the_grocery_list(client, app_db):
    html = page(client, "/recipes/2?servings=8")
    first_side = side_cards(html)[0]
    side_id = next(s["id"] for s in db.list_sides(db_path=app_db) if s["name"] == first_side)
    # The side's button adds it at the servings the main is shown at
    assert f'action="/plan/add/{side_id}"' in html

    response = client.post(f"/plan/add/{side_id}",
                           data={"next": "/recipes/2?servings=8#sides", "servings": "8"})

    assert response.headers["Location"].endswith("/recipes/2?servings=8#sides")
    assert db.plan_servings(db_path=app_db) == {side_id: 8}
    side_recipe = db.get_recipe(side_id, db_path=app_db)
    grocery = page(client, "/grocery")
    first_ingredient = side_recipe["ingredients"][0]["name"].split(",")[0]
    assert first_ingredient.lower() in grocery.lower()


def test_grocery_list_merges_main_and_side(client, app_db):
    rice = next(s["id"] for s in db.list_sides(db_path=app_db) if s["name"] == "Cilantro Lime Rice")
    client.post("/plan/add/2", data={"next": "/"})
    client.post(f"/plan/add/{rice}", data={"next": "/"})

    grocery = page(client, "/grocery")
    assert "long-grain white rice" in grocery
    assert "cilantro" in grocery


# --- The form ---

def test_form_has_side_fields(client):
    html = page(client, "/recipes/new")
    assert 'name="cuisine"' in html
    assert 'name="side_type"' in html
    assert 'name="fridge_days"' in html


NEW_SIDE = {
    "name": "Herby Couscous",
    "servings": "4",
    "amount": ["1"], "unit": ["cup"], "ingredient_name": ["couscous"],
    "steps": "Cook.",
    "tags": "",
    "meal_type": "side",
    "side_type": "",
    "cuisine": "mediterranean",
    "fridge_days": "3",
}


def test_saving_a_side_from_the_form(client, app_db):
    response = client.post("/recipes/new", data=NEW_SIDE)
    recipe_id = int(response.headers["Location"].rsplit("/", 1)[1])
    recipe = db.get_recipe(recipe_id, db_path=app_db)

    assert recipe["side_type"] == "starch"         # guessed
    assert recipe["cuisine"] == "mediterranean"
    assert recipe["fridge_days"] == 3


@pytest.mark.parametrize("bad", ["abc", "-1", "2.5", "999"])
def test_bad_fridge_days_shows_an_error(client, bad):
    response = client.post("/recipes/new", data={**NEW_SIDE, "fridge_days": bad})
    assert response.status_code == 400
    assert "Fridge days must be a whole number" in response.get_data(as_text=True)


def test_editing_cuisine_and_clearing_fridge_days(client, app_db):
    rice = next(s for s in db.list_sides(db_path=app_db) if s["name"] == "Cilantro Lime Rice")
    form = page(client, f"/recipes/{rice['id']}/edit")
    assert '<option value="mexican" selected>' in form
    assert 'value="4"' in form

    client.post(f"/recipes/{rice['id']}/edit", data={
        **NEW_SIDE, "name": "Cilantro Lime Rice", "side_type": "starch",
        "cuisine": "asian", "fridge_days": "",
    })

    recipe = db.get_recipe(rice["id"], db_path=app_db)
    assert recipe["cuisine"] == "asian"
    assert recipe["fridge_days"] is None


def test_editing_a_main_cuisine(client, app_db):
    client.post("/recipes/3/edit", data={
        "name": "Chicken Stroganoff", "servings": "4",
        "amount": ["1"], "unit": ["lb"], "ingredient_name": ["chicken"],
        "steps": "Cook.", "tags": "", "meal_type": "main", "cuisine": "american",
    })
    assert db.get_recipe(3, db_path=app_db)["cuisine"] == "american"
    assert '<span class="label cuisine">american</span>' in page(client, "/recipes/3")
