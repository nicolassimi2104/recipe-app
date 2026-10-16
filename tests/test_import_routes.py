"""Tests for the /import pages: preview, save, duplicates and link import.
The link import is faked, so no real network calls are made."""

import json

import pytest

import db
import importer
from app import create_app


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    # create_app also imports the 4 seed recipes into this temp database
    return create_app(db_path=db_path).test_client()


def recipe_json(name="Pancakes", **changes):
    data = {
        "name": name,
        "servings": 4,
        "ingredients": [{"amount": "1 1/2", "unit": "cup", "name": "flour"}],
        "steps": ["Mix.", "Cook."],
    }
    data.update(changes)
    return data


def names(db_path):
    return [r["name"] for r in db.list_recipes(db_path=db_path)]


def test_import_page_loads_with_prompt_and_both_options(client):
    page = client.get("/import").get_data(as_text=True)

    assert "A. Paste JSON" in page
    assert "B. From a link" in page
    assert "Copy prompt" in page
    assert "Output ONLY valid JSON" in page


def test_home_page_links_to_import(client):
    assert 'href="/import"' in client.get("/").get_data(as_text=True)


def test_preview_shows_recipe_without_saving(client, db_path):
    before = names(db_path)

    response = client.post("/import/preview", data={"json_text": json.dumps(recipe_json())})
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Check before saving" in page
    assert "1 1/2 cup flour" in page
    assert "Save recipe" in page
    assert names(db_path) == before   # nothing saved yet


def test_preview_with_errors_keeps_the_text(client):
    bad = json.dumps([recipe_json(), {"name": "Soup"}])

    response = client.post("/import/preview", data={"json_text": bad})
    page = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Recipe 2 (&#34;Soup&#34;): missing &#39;servings&#39;" in page
    assert "Check before saving" not in page
    assert "Pancakes" in page   # what they pasted is still in the box


def test_invalid_json_does_not_crash(client):
    response = client.post("/import/preview", data={"json_text": "{oops"})

    assert response.status_code == 400
    assert "isn&#39;t valid JSON" in response.get_data(as_text=True)


def test_save_one_goes_to_the_recipe(client, db_path):
    preview = importer.recipes_to_json(importer.parse_json_text(json.dumps(recipe_json()))[0])

    response = client.post("/import/save", data={"recipes_json": preview})

    new_id = next(r["id"] for r in db.list_recipes(db_path=db_path) if r["name"] == "Pancakes")
    assert response.status_code == 302
    assert response.headers["Location"] == f"/recipes/{new_id}"
    assert db.get_recipe(new_id, db_path=db_path)["steps"] == "Mix.\nCook."


def test_save_several_goes_home_with_a_note(client, db_path):
    data = json.dumps([recipe_json("Pancakes"), recipe_json("Waffles")])

    response = client.post("/import/save", data={"recipes_json": data}, follow_redirects=True)

    assert response.request.path == "/"
    assert "Imported 2 recipes." in response.get_data(as_text=True)
    assert {"Pancakes", "Waffles"} <= set(names(db_path))


def test_save_rechecks_the_json(client, db_path):
    before = names(db_path)

    response = client.post("/import/save", data={"recipes_json": '{"name": "x"}'})

    assert response.status_code == 400
    assert names(db_path) == before


def test_duplicate_is_flagged_in_preview(client):
    data = json.dumps(recipe_json("Chicken Stroganoff"))   # a seed recipe

    page = client.post("/import/preview", data={"json_text": data}).get_data(as_text=True)

    assert "already have a recipe called" in page
    assert 'name="save_anyway" value="0"' in page


def test_duplicate_is_skipped_by_default(client, db_path):
    data = json.dumps([recipe_json("Chicken Stroganoff"), recipe_json("Waffles")])

    response = client.post("/import/save", data={"recipes_json": data}, follow_redirects=True)

    assert names(db_path).count("Chicken Stroganoff") == 1
    assert "Waffles" in names(db_path)
    # Only one was saved, so we go straight to it
    assert response.request.path.startswith("/recipes/")


def test_skipped_duplicates_are_mentioned_on_home(client, db_path):
    data = json.dumps([recipe_json("Chicken Stroganoff"), recipe_json("Waffles"), recipe_json("Crepes")])

    page = client.post("/import/save", data={"recipes_json": data}, follow_redirects=True).get_data(as_text=True)

    assert "Imported 2 recipes. Skipped 1 duplicate." in page


def test_save_anyway_saves_the_duplicate(client, db_path):
    data = json.dumps(recipe_json("Chicken Stroganoff"))

    response = client.post("/import/save", data={"recipes_json": data, "save_anyway": "0"})

    assert response.status_code == 302
    assert names(db_path).count("Chicken Stroganoff") == 2


def test_only_duplicates_saves_nothing_and_explains(client, db_path):
    data = json.dumps(recipe_json("Chicken Stroganoff"))

    response = client.post("/import/save", data={"recipes_json": data})
    page = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Nothing was saved" in page
    assert "Save anyway" in page
    assert names(db_path).count("Chicken Stroganoff") == 1


def test_url_import_shows_preview_and_fills_json_box(client, monkeypatch):
    recipe = {"name": "Banana Bread", "servings": 8, "tags": [], "steps": "Bake.",
              "ingredients": [{"amount": "3", "unit": "", "name": "bananas"}]}
    monkeypatch.setattr(importer, "recipe_from_url", lambda url: (recipe, ["Check the servings."]))

    response = client.post("/import/url", data={"url": "https://example.com/bread"})
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Check before saving" in page
    assert "3 bananas" in page
    assert "Check the servings." in page
    assert "&#34;name&#34;: &#34;Banana Bread&#34;" in page   # JSON box is filled in for editing


def test_url_import_failure_points_to_option_a(client, monkeypatch):
    def fail(url):
        raise importer.ImportFailed("Couldn't reach that site.")
    monkeypatch.setattr(importer, "recipe_from_url", fail)

    response = client.post("/import/url", data={"url": "https://example.com/x"})
    page = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "Couldn&#39;t reach that site." in page
    assert "option A" in page
    assert 'value="https://example.com/x"' in page   # the link stays in the box


def test_url_import_rejects_non_web_links_without_network(client, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("should not try to download")
    monkeypatch.setattr(importer.urllib.request, "urlopen", no_network)

    response = client.post("/import/url", data={"url": "file:///C:/Windows/win.ini"})

    assert response.status_code == 400
    assert "start with http" in response.get_data(as_text=True)
