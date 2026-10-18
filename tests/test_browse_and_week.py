"""Tests for browsing by protein, labels on the pages, and "Add to this week"."""

import json

import pytest

import db
from app import create_app

# Seed recipes and their guessed labels:
#   1 Ham, Spinach & Onion Quiche    pork + eggs-other, breakfast (serves 6)
#   2 Mushroom Butter Sauce Chicken  chicken, main (serves 4)
#   3 Chicken Stroganoff             chicken, main (serves 4), tagged quick
#   4 Greek Yogurt Parfait Bowls     vegetarian, breakfast (serves 5)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    return create_app(db_path=db_path).test_client()


def page(client, url):
    return client.get(url).get_data(as_text=True)


def recipe_list(html):
    """Just the recipe cards part of the home page."""
    return html.split('class="recipe-list"')[1] if 'class="recipe-list"' in html else ""


# --- Seed recipes are labelled ---

def test_seed_recipes_are_labelled(db_path, client):
    labels_by_name = {r["name"]: (r["proteins"], r["meal_type"]) for r in db.list_recipes(db_path=db_path)}

    assert labels_by_name["Chicken Stroganoff"] == (["chicken"], "main")
    assert labels_by_name["Ham, Spinach & Onion Quiche (crustless)"] == (["pork", "eggs-other"], "breakfast")
    assert labels_by_name["Greek Yogurt Protein Parfait Bowls"] == (["vegetarian"], "breakfast")


# --- Protein chips on the home page ---

def test_home_shows_protein_chips_with_counts(client):
    html = page(client, "/")

    assert 'aria-label="Filter by protein"' in html
    assert 'All <span class="count">4</span>' in html
    assert 'Chicken <span class="count">2</span>' in html
    assert 'Beef <span class="count">0</span>' in html
    assert 'Fish &amp; seafood <span class="count">0</span>' in html
    assert 'Eggs/other <span class="count">1</span>' in html


def test_protein_chip_filters_recipes(client):
    html = page(client, "/?protein=chicken")
    cards = recipe_list(html)

    assert "Chicken Stroganoff" in cards
    assert "Mushroom Butter Sauce" in cards
    assert "Parfait" not in cards
    assert "2 of 4 recipes" in html
    assert 'class="chip active"' in html


def test_protein_chip_combines_with_search_and_tags(client):
    # Chicken AND tagged quick: only the stroganoff
    html = page(client, "/?protein=chicken&tag=quick")
    assert "Chicken Stroganoff" in recipe_list(html)
    assert "Mushroom Butter Sauce" not in recipe_list(html)

    # Search "mushroom" + chicken: both chicken dishes have mushrooms
    html = page(client, "/?q=mushroom&protein=chicken")
    assert "2 of 4 recipes" in html


def test_chip_counts_follow_the_search(client):
    # Searching "yogurt" finds the quiche and the parfait
    html = page(client, "/?q=yogurt")

    assert 'All <span class="count">2</span>' in html
    assert 'Chicken <span class="count">0</span>' in html
    assert 'Vegetarian <span class="count">1</span>' in html


def test_chip_and_tag_links_keep_each_other(client):
    html = page(client, "/?q=chick&protein=chicken&tag=dinner")

    # Protein chips keep the search and tags
    assert 'href="/?q=chick&amp;protein=beef&amp;tag=dinner"' in html
    assert 'href="/?q=chick&amp;tag=dinner"' in html          # the "All" chip
    # Tag pills keep the protein
    assert 'href="/?q=chick&amp;protein=chicken&amp;tag=dinner&amp;tag=quick"' in html
    # The search form keeps it too
    assert '<input type="hidden" name="protein" value="chicken">' in html


def test_protein_with_no_matches(client):
    html = page(client, "/?protein=beef")

    assert "0 of 4 recipes" in html
    assert "No Beef recipes yet." in html
    assert "Clear filters" in html


def test_protein_with_search_and_no_matches(client):
    html = page(client, "/?protein=fish&q=tofu")

    assert 'No Fish &amp; seafood recipes match "tofu".' in html


def test_unknown_protein_shows_everything(client):
    html = page(client, "/?protein=dragon")

    assert "4 recipes" in html
    assert "Clear filters" not in html


def test_cards_and_detail_page_show_labels(client):
    assert '<span class="label protein-chicken">Chicken</span>' in page(client, "/")

    detail = page(client, "/recipes/1")
    assert 'href="/?protein=pork" class="label protein-pork">Pork</a>' in detail
    assert '<span class="label meal">breakfast</span>' in detail


# --- Labels on the recipe form ---

NEW_RECIPE = {
    "name": "Beef Tacos",
    "servings": "4",
    "amount": ["1"], "unit": ["lb"], "ingredient_name": ["ground beef"],
    "steps": "Cook.",
    "tags": "",
}


def test_new_form_has_label_fields(client):
    html = page(client, "/recipes/new")

    assert 'name="protein" value="fish"' in html
    assert '<option value="">Guess for me</option>' in html
    assert "guess_labels" not in html   # only when editing


def test_new_recipe_with_blank_labels_is_guessed(client, db_path):
    client.post("/recipes/new", data=NEW_RECIPE)
    recipe = db.get_recipe(5, db_path=db_path)

    assert recipe["proteins"] == ["beef"]
    assert recipe["meal_type"] == "main"
    assert recipe["proteins_by_hand"] == 0


def test_new_recipe_with_picked_labels_keeps_them(client, db_path):
    client.post("/recipes/new", data={**NEW_RECIPE, "protein": ["pork", "beef"], "meal_type": "side"})
    recipe = db.get_recipe(5, db_path=db_path)

    assert recipe["proteins"] == ["beef", "pork"]
    assert recipe["meal_type"] == "side"
    assert recipe["proteins_by_hand"] == 1


def edit_form(recipe, **changes):
    """The edit form as the browser would send it back, unchanged unless told."""
    data = {
        "name": recipe["name"],
        "servings": str(recipe["servings"]),
        "amount": [i["amount"] for i in recipe["ingredients"]],
        "unit": [i["unit"] for i in recipe["ingredients"]],
        "ingredient_name": [i["name"] for i in recipe["ingredients"]],
        "steps": recipe["steps"],
        "tags": ", ".join(recipe["tags"]),
        "protein": recipe["proteins"],
        "meal_type": recipe["meal_type"],
    }
    data.update(changes)
    return data


def test_edit_form_is_prefilled_with_labels(client):
    html = page(client, "/recipes/3/edit")

    assert 'name="protein" value="chicken" checked' in html
    assert '<option value="main" selected>' in html
    assert 'name="guess_labels"' in html


def test_editing_ingredients_re_guesses_untouched_labels(client, db_path):
    recipe = db.get_recipe(3, db_path=db_path)
    # Swap the chicken for beef but leave the label boxes as they were
    client.post("/recipes/3/edit", data=edit_form(recipe, ingredient_name=["beef sirloin"],
                                                  amount=["1"], unit=["lb"]))

    assert db.get_recipe(3, db_path=db_path)["proteins"] == ["beef"]


def test_changing_a_label_by_hand_sticks(client, db_path):
    recipe = db.get_recipe(3, db_path=db_path)
    client.post("/recipes/3/edit", data=edit_form(recipe, protein=["chicken", "fish"]))
    # Edit it again later, changing only the name: the hand-picked label stays
    recipe = db.get_recipe(3, db_path=db_path)
    client.post("/recipes/3/edit", data=edit_form(recipe, name="Stroganoff 2"))

    recipe = db.get_recipe(3, db_path=db_path)
    assert recipe["proteins"] == ["chicken", "fish"]
    assert recipe["proteins_by_hand"] == 1
    assert recipe["meal_type_by_hand"] == 0   # meal type wasn't touched


def test_guess_again_box_forgets_hand_picked_labels(client, db_path):
    recipe = db.get_recipe(3, db_path=db_path)
    client.post("/recipes/3/edit", data=edit_form(recipe, protein=["fish"], meal_type="dessert"))
    recipe = db.get_recipe(3, db_path=db_path)
    client.post("/recipes/3/edit", data=edit_form(recipe, guess_labels="1"))

    recipe = db.get_recipe(3, db_path=db_path)
    assert recipe["proteins"] == ["chicken"]
    assert recipe["meal_type"] == "main"


def test_imported_recipes_are_labelled(client, db_path):
    recipes = [{"name": "Salmon Bake", "servings": 2, "tags": [], "steps": ["Bake."],
                "ingredients": [{"amount": "1", "unit": "lb", "name": "salmon fillets"}]}]
    client.post("/import/save", data={"recipes_json": json.dumps(recipes)})

    (salmon,) = [r for r in db.list_recipes(db_path=db_path) if r["name"] == "Salmon Bake"]
    assert salmon["proteins"] == ["fish"]


# --- Add to this week ---

def test_cards_have_add_buttons_and_the_bar_shows_zero(client):
    html = page(client, "/")

    assert html.count("+ Add to this week") == 4
    assert 'action="/plan/add/3"' in html
    assert "This week (0)" in html
    assert 'href="/grocery">Grocery list' not in html   # nothing to shop for yet


def test_add_toggles_the_button_and_updates_the_bar(client, db_path):
    response = client.post("/plan/add/3", data={"next": "/?protein=chicken#recipe-3"})

    # Back to the same page and card
    assert response.status_code == 302
    assert response.headers["Location"] == "/?protein=chicken#recipe-3"
    assert db.plan_servings(db_path=db_path) == {3: 4}   # the recipe's own servings

    html = page(client, "/")
    assert "On this week's plan" in html
    assert 'action="/plan/remove/3"' in html
    assert html.count("+ Add to this week") == 3
    assert "This week (1)" in html
    assert 'href="/grocery">Grocery list' in html


def test_tapping_again_removes_it(client, db_path):
    client.post("/plan/add/3", data={"next": "/"})
    client.post("/plan/remove/3", data={"next": "/"})

    assert db.plan_servings(db_path=db_path) == {}
    assert "This week (0)" in page(client, "/")


def test_add_from_the_recipe_page_uses_the_scaled_servings(client, db_path):
    html = page(client, "/recipes/2?servings=8")
    assert '<input type="hidden" name="servings" value="8">' in html

    client.post("/plan/add/2", data={"servings": "8", "next": "/recipes/2?servings=8"})
    assert db.plan_servings(db_path=db_path) == {2: 8}
    assert "On the plan for 8 servings." in page(client, "/recipes/2")


@pytest.mark.parametrize("servings", ["abc", "0", "-3", "99999"])
def test_bad_servings_fall_back_to_the_recipes_own(client, db_path, servings):
    client.post("/plan/add/2", data={"servings": servings, "next": "/"})
    assert db.plan_servings(db_path=db_path) == {2: 4}


def test_adding_a_missing_recipe_is_404(client):
    assert client.post("/plan/add/999", data={"next": "/"}).status_code == 404


def test_add_never_redirects_to_another_site(client):
    response = client.post("/plan/add/2", data={"next": "https://evil.example/"})
    assert response.headers["Location"] == "/"


def test_add_and_remove_need_a_post(client):
    assert client.get("/plan/add/2").status_code == 405
    assert client.get("/plan/remove/2").status_code == 405


# --- The plan page ---

def test_plan_page_saves_servings(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    client.post("/plan/add/3", data={"next": "/"})

    response = client.post("/plan/servings", data={"servings_2": "10", "servings_3": "nope"})

    assert response.headers["Location"] == "/plan"
    assert db.plan_servings(db_path=db_path) == {2: 10, 3: 4}   # bad value: unchanged


def test_make_grocery_list_button_saves_then_opens_the_list(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    response = client.post("/plan/servings", data={"servings_2": "8", "then": "grocery", "units": "metric"})

    assert response.headers["Location"] == "/grocery?units=metric"
    assert db.plan_servings(db_path=db_path) == {2: 8}


def test_remove_on_the_plan_page(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    html = page(client, "/plan")
    assert 'action="/plan/remove/2"' in html

    client.post("/plan/remove/2", data={"next": "/plan"})
    assert "Nothing planned yet" in page(client, "/plan")


def test_clear_plan(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    client.post("/plan/add/3", data={"next": "/"})

    response = client.post("/plan/clear")

    assert response.headers["Location"] == "/plan"
    assert db.plan_servings(db_path=db_path) == {}


def test_plan_survives_a_restart(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    restarted = create_app(db_path=db_path).test_client()

    assert "This week (1)" in page(restarted, "/")


# --- Grocery list from the saved plan ---

def test_grocery_list_uses_the_saved_plan(client):
    client.post("/plan/add/2", data={"next": "/"})
    client.post("/plan/add/3", data={"next": "/"})
    html = page(client, "/grocery")

    assert "<span>18 oz mushrooms, sliced</span>" in html   # merged: 10 + 8
    assert "<h3>Produce</h3>" in html                       # aisles still work
    assert 'data-key="mushrooms, sliced"' in html           # tick keys still work
    assert 'data-plan="2x4,3x4"' in html                    # ticks remembered per plan


def test_grocery_list_follows_servings_changes(client):
    client.post("/plan/add/2", data={"next": "/"})
    client.post("/plan/servings", data={"servings_2": "8"})
    html = page(client, "/grocery")

    assert "<span>1 1/4 lb mushrooms, sliced</span>" in html   # 20 oz
    assert 'data-plan="2x8"' in html


def test_deleted_recipe_drops_off_the_grocery_list(client, db_path):
    client.post("/plan/add/2", data={"next": "/"})
    client.post("/recipes/2/delete")

    html = page(client, "/grocery")
    assert "No recipes on this week's plan yet." in html


# --- Old plan links (from when the plan lived in the URL) ---

@pytest.mark.parametrize("query", [
    "recipe=2&servings_2=8", "recipe=abc", "recipe=999", "recipe=2&servings_2=abc",
    "recipe=2&recipe=2", "recipe=2&servings_2=0", "recipe=2&units=metric",
])
@pytest.mark.parametrize("path", ["/plan", "/grocery"])
def test_old_plan_links_do_not_crash(client, path, query):
    assert client.get(f"{path}?{query}").status_code == 200


def test_old_plan_link_offers_to_load_its_recipes(client, db_path):
    html = page(client, "/plan?recipe=2&servings_2=8&recipe=3")

    assert "This link is from an older plan with" in html
    assert "Mushroom Butter Sauce Chicken &amp; Potatoes, Chicken Stroganoff." in html
    assert 'action="/plan/load"' in html
    assert db.plan_servings(db_path=db_path) == {}      # just looking changes nothing

    client.post("/plan/load", data={"recipe": ["2", "3"], "servings_2": "8"})
    assert db.plan_servings(db_path=db_path) == {2: 8, 3: 4}


def test_old_grocery_link_explains_and_links_to_loading(client):
    html = page(client, "/grocery?recipe=2&servings_2=8")

    assert "This is an old grocery list link." in html
    assert 'href="/plan?recipe=2&amp;servings_2=8"' in html


def test_old_link_with_no_real_recipes_shows_no_note(client):
    assert "older plan" not in page(client, "/plan?recipe=999")
