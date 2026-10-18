"""Tests for the web pages: they load, the forms save, and delete needs confirmation."""

import pytest

import db
from app import create_app


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    # create_app also imports the 4 seed recipes into this temp database
    app = create_app(db_path=db_path)
    return app.test_client()


def find_recipe_id(db_path, name):
    return next(r["id"] for r in db.list_recipes(db_path=db_path) if r["name"] == name)


# The same data a browser would send when you fill in the form
NEW_RECIPE_FORM = {
    "name": "Toast",
    "servings": "2",
    "amount": ["2", "", ""],
    "unit": ["slice", "", ""],
    "ingredient_name": ["bread", "butter", ""],  # 3rd row left empty: should be skipped
    "steps": "Toast the bread.\r\n\r\nButter it.",
    "tags": "Breakfast, quick, ,breakfast",
}


def test_home_lists_seed_recipes_with_add_button(client):
    page = client.get("/").get_data(as_text=True)

    assert "Chicken Stroganoff" in page
    assert "Serves 4" in page
    assert "one-pan" in page
    assert "Add recipe" in page


def test_detail_page_shows_blank_amount_cleanly(client, db_path):
    recipe_id = find_recipe_id(db_path, "Ham, Spinach & Onion Quiche (crustless)")

    page = client.get(f"/recipes/{recipe_id}").get_data(as_text=True)

    assert "<li>salt and pepper</li>" in page
    assert "<li>1/2 cup heavy cream</li>" in page
    assert "<li>Rest 5 min before slicing.</li>" in page


def test_missing_recipe_is_404(client):
    assert client.get("/recipes/999").status_code == 404
    assert client.get("/recipes/999/edit").status_code == 404
    assert client.get("/recipes/999/delete").status_code == 404


def test_add_form_loads(client):
    page = client.get("/recipes/new").get_data(as_text=True)

    assert "Add recipe" in page
    assert page.count('class="ingredient-row"') >= 3


def test_add_recipe_through_form(client, db_path):
    response = client.post("/recipes/new", data=NEW_RECIPE_FORM)

    assert response.status_code == 302  # redirects to the new recipe's page
    recipe = db.get_recipe(find_recipe_id(db_path, "Toast"), db_path=db_path)
    assert recipe["servings"] == 2
    assert recipe["ingredients"] == [
        {"amount": "2", "unit": "slice", "name": "bread"},
        {"amount": "", "unit": "", "name": "butter"},
    ]
    assert recipe["steps"] == "Toast the bread.\nButter it."
    assert recipe["tags"] == ["breakfast", "quick"]


def test_add_recipe_with_missing_name_shows_error(client, db_path):
    form = dict(NEW_RECIPE_FORM, name="  ")

    response = client.post("/recipes/new", data=form)

    assert response.status_code == 400
    assert "Please enter a recipe name." in response.get_data(as_text=True)
    assert len(db.list_recipes(db_path=db_path)) == 4  # nothing new saved


def test_edit_form_is_prefilled(client, db_path):
    recipe_id = find_recipe_id(db_path, "Chicken Stroganoff")

    page = client.get(f"/recipes/{recipe_id}/edit").get_data(as_text=True)

    assert "Edit recipe" in page
    assert 'value="sour cream"' in page
    assert 'value="chicken, dinner, quick"' in page


def test_edit_recipe_through_form(client, db_path):
    recipe_id = find_recipe_id(db_path, "Chicken Stroganoff")

    form = dict(NEW_RECIPE_FORM, name="Beef Stroganoff", servings="6")
    response = client.post(f"/recipes/{recipe_id}/edit", data=form)

    assert response.status_code == 302
    recipe = db.get_recipe(recipe_id, db_path=db_path)
    assert recipe["name"] == "Beef Stroganoff"
    assert recipe["servings"] == 6


def test_delete_page_asks_first_and_does_not_delete(client, db_path):
    recipe_id = find_recipe_id(db_path, "Chicken Stroganoff")

    page = client.get(f"/recipes/{recipe_id}/delete").get_data(as_text=True)

    assert "Are you sure" in page
    assert db.get_recipe(recipe_id, db_path=db_path) is not None  # still there


def test_delete_after_confirming(client, db_path):
    recipe_id = find_recipe_id(db_path, "Chicken Stroganoff")

    response = client.post(f"/recipes/{recipe_id}/delete")

    assert response.status_code == 302
    assert db.get_recipe(recipe_id, db_path=db_path) is None
    assert len(db.list_recipes(db_path=db_path)) == 3


def test_restarting_app_does_not_duplicate_seed(db_path):
    create_app(db_path=db_path)
    create_app(db_path=db_path)  # second start

    assert len(db.list_recipes(db_path=db_path)) == 4


# --- Scaling on the detail page ---
# Recipe 1 is the first seed recipe: the quiche, which serves 6.

def test_scale_recipe_to_12_servings(client, db_path):
    page = client.get("/recipes/1?servings=12").get_data(as_text=True)

    assert "Ham, Spinach &amp; Onion Quiche" in page
    assert "<li>12 eggs</li>" in page                      # 6 doubled
    assert "<li>1 cup heavy cream</li>" in page            # 1/2 doubled
    assert "<li>1 1/2 cup shredded cheese" in page         # 3/4 doubled
    assert "<li>1 small onion, diced</li>" in page         # 1/2 doubled
    assert "<li>salt and pepper</li>" in page              # no amount: unchanged
    assert "Scaled from 6 to 12 servings" in page
    assert 'name="servings" value="12"' in page


def test_scaling_does_not_change_saved_recipe(client, db_path):
    client.get("/recipes/1?servings=12")

    recipe = db.get_recipe(1, db_path=db_path)
    assert recipe["servings"] == 6
    assert recipe["ingredients"][1]["amount"] == "1/2"


def test_scale_down_uses_fractions(client):
    page = client.get("/recipes/1?servings=2").get_data(as_text=True)

    assert "<li>2 eggs</li>" in page                       # 6 / 3
    assert "<li>1/4 cup shredded cheese" in page           # 3/4 / 3
    assert "<li>1/8 small onion, diced</li>" in page       # 1/2 / 3 = 1/6 -> nearest 1/8


def test_scaling_simplifies_units(client):
    # Quiche has 2 tbsp cream cheese: doubled that's 4 tbsp = 1/4 cup
    page = client.get("/recipes/1?servings=12").get_data(as_text=True)

    assert "<li>1/4 cup cream cheese, softened</li>" in page


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "2.5", "", "99999", "²"])
def test_bad_servings_fall_back_to_original(client, bad):
    response = client.get(f"/recipes/1?servings={bad}")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "<li>6 eggs</li>" in page
    assert "<li>1/2 cup heavy cream</li>" in page
    assert 'name="servings" value="6"' in page
    assert "Scaled from" not in page


def test_detail_page_without_servings_shows_scale_box(client):
    page = client.get("/recipes/1").get_data(as_text=True)

    assert 'name="servings" value="6"' in page
    assert "Scale</button>" in page
    assert "Scaled from" not in page


# --- This week's plan and grocery list ---
# Seed ids: 1 quiche (serves 6), 2 mushroom chicken (4), 3 stroganoff (4), 4 parfait (5).

def plan_week(client, servings_by_id):
    """Put recipes on the plan the way the buttons do: {recipe_id: servings}."""
    for recipe_id, servings in servings_by_id.items():
        response = client.post(f"/plan/add/{recipe_id}", data={"servings": servings, "next": "/"})
        assert response.status_code == 302


def test_header_links_to_plan_page(client):
    assert 'href="/plan"' in client.get("/").get_data(as_text=True)


def test_empty_plan_page_points_to_recipes(client):
    page = client.get("/plan").get_data(as_text=True)

    assert "Nothing planned yet" in page
    assert "This week (0)" in page


def test_plan_page_shows_saved_recipes_with_servings(client):
    plan_week(client, {2: 8})
    page = client.get("/plan").get_data(as_text=True)

    assert "Mushroom Butter Sauce Chicken" in page
    assert "Chicken Stroganoff" not in page.split("<main>")[1]   # not planned
    assert 'name="servings_2" value="8"' in page
    assert "Make grocery list" in page
    assert "Clear plan" in page


def test_grocery_list_merges_shared_ingredients(client):
    plan_week(client, {2: 4, 3: 4})
    page = client.get("/grocery").get_data(as_text=True)

    assert "<span>18 oz mushrooms, sliced</span>" in page   # 10 + 8
    assert "<span>1 tsp salt</span>" in page
    assert "<span>egg noodles</span>" in page              # no amount: shown once
    assert page.count("mushrooms, sliced</span>") == 1      # one line on the list


def test_grocery_list_scales_each_recipe(client):
    # Recipe 2 doubled (4 -> 8), recipe 3 as written
    plan_week(client, {2: 8, 3: 4})
    page = client.get("/grocery").get_data(as_text=True)

    assert "<span>1 3/4 lb mushrooms, sliced</span>" in page   # 20 + 8 = 28 oz
    assert "<span>1/2 cup butter</span>" in page               # 8 tbsp
    assert "(8 servings)" in page


def test_grocery_list_rounds_up(client):
    # Quiche (serves 6) at 5 servings: 6 eggs x 5/6 = 5 exactly, but
    # 1/2 cup cream x 5/6 = 5/12 cup (6 2/3 tbsp), which rounds UP to 7 tbsp
    plan_week(client, {1: 5})
    page = client.get("/grocery").get_data(as_text=True)

    assert "<span>5 eggs</span>" in page
    assert "<span>7 tbsp heavy cream</span>" in page


def test_grocery_list_with_nothing_planned(client):
    response = client.get("/grocery")

    assert response.status_code == 200
    assert "No recipes on this week's plan yet." in response.get_data(as_text=True)


# --- US / Metric switch ---

def test_detail_page_in_metric(client):
    page = client.get("/recipes/1?units=metric").get_data(as_text=True)

    assert "<li>120 ml heavy cream</li>" in page           # 1/2 cup
    assert "<li>30 ml cream cheese, softened</li>" in page # 2 tbsp
    assert "<li>6 eggs</li>" in page                       # counts stay as they are
    assert "Converted to metric" in page


def test_metric_and_scaling_together(client):
    page = client.get("/recipes/1?servings=12&units=metric").get_data(as_text=True)

    assert "<li>240 ml heavy cream</li>" in page           # 1 cup
    assert "<li>12 eggs</li>" in page


def test_us_is_the_default_and_bad_values_fall_back_to_it(client):
    for query in ["", "?units=us", "?units=banana"]:
        page = client.get(f"/recipes/1{query}").get_data(as_text=True)
        assert "<li>1/2 cup heavy cream</li>" in page
        assert "Converted to metric" not in page


def test_scale_form_keeps_metric(client):
    metric = client.get("/recipes/1?units=metric").get_data(as_text=True)
    us = client.get("/recipes/1").get_data(as_text=True)

    assert '<input type="hidden" name="units" value="metric">' in metric
    assert 'name="units"' not in us


def test_units_links_keep_servings(client):
    page = client.get("/recipes/1?servings=12").get_data(as_text=True)

    assert 'href="/recipes/1?servings=12&amp;units=metric"' in page
    assert 'href="/recipes/1?servings=12" class="current"' in page


def test_back_to_original_keeps_metric(client):
    page = client.get("/recipes/1?servings=12&units=metric").get_data(as_text=True)

    assert 'href="/recipes/1?units=metric">Back to original' in page


def test_grocery_list_in_metric(client):
    plan_week(client, {2: 4})
    page = client.get("/grocery?units=metric").get_data(as_text=True)

    assert "<span>290 g mushrooms, sliced</span>" in page  # 10 oz, rounded up
    assert "/recipes/2?servings=4&amp;units=metric" in page  # recipe links keep metric
    assert 'href="/grocery">US</a>' in page                 # switch back to US
    assert 'href="/plan?units=metric"' in page              # "Change recipes" keeps metric


def test_plan_form_keeps_metric(client):
    plan_week(client, {2: 8})
    page = client.get("/plan?units=metric").get_data(as_text=True)

    assert '<input type="hidden" name="units" value="metric">' in page


# --- Grocery list polish: aisles, ticks, copy as text ---

def test_grocery_list_has_aisle_headings_in_order(client):
    plan_week(client, {1: 6})   # quiche
    page = client.get("/grocery").get_data(as_text=True)

    produce = page.index("<h3>Produce</h3>")
    dairy = page.index("<h3>Dairy &amp; Eggs</h3>")
    meat = page.index("<h3>Meat &amp; Seafood</h3>")
    assert produce < dairy < meat
    assert "<h3>Frozen</h3>" not in page                   # empty aisles are hidden
    # diced ham is under the Meat heading
    assert page.index("diced ham") > meat


def test_grocery_list_has_tick_keys_copy_and_clear(client):
    plan_week(client, {1: 6})
    page = client.get("/grocery").get_data(as_text=True)

    assert 'data-key="diced ham"' in page
    assert "Copy as text" in page
    assert "Clear checks" in page
    assert "grocery.js" in page
    # The text box starts with the full list (no JavaScript needed to read it)
    assert "Meat &amp; Seafood\n- " in page


# --- Home page search and tag filter ---

def test_home_search_by_name_and_ingredient(client):
    # "stroganoff" is in a name; "noodles" only in Chicken Stroganoff's ingredients
    for q in ("stroganoff", "NOODLES"):
        page = client.get("/", query_string={"q": q}).get_data(as_text=True)
        assert "Chicken Stroganoff" in page
        assert "Mushroom Butter Sauce" not in page
        assert "1 of 4 recipes" in page
        assert f'value="{q}"' in page  # search box keeps what you typed


def test_home_multi_tag_and_search_through_query_params(client):
    page = client.get("/?q=chick&tag=dinner&tag=one-pan").get_data(as_text=True)

    assert "Mushroom Butter Sauce Chicken &amp; Potatoes" in page
    assert "Chicken Stroganoff" not in page   # dinner + chicken, but not one-pan
    assert "1 of 4 recipes" in page
    assert "Clear filters" in page
    # Active tags are kept in the search form as hidden fields
    assert '<input type="hidden" name="tag" value="dinner">' in page
    assert '<input type="hidden" name="tag" value="one-pan">' in page


def test_home_tag_pills_toggle_on_and_off(client):
    page = client.get("/?q=chick&tag=dinner").get_data(as_text=True)

    # Clicking an inactive pill adds it, keeping the search and other tags
    assert 'href="/?q=chick&amp;tag=dinner&amp;tag=quick"' in page
    # Clicking the active pill removes it (and only it)
    assert 'href="/?q=chick"' in page
    assert 'class="tag-pill active"' in page


def test_home_no_results_message(client):
    page = client.get("/?q=tofu&tag=breakfast").get_data(as_text=True)

    assert "0 of 4 recipes" in page
    assert 'No recipes match "tofu" with tag breakfast.' in page
    assert "Clear filters" in page


def test_home_without_filters_has_no_clear_link(client):
    page = client.get("/").get_data(as_text=True)

    assert "4 recipes" in page
    assert "Clear filters" not in page
