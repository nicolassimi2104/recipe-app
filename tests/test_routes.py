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
