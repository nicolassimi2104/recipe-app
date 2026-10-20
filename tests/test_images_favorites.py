"""Tests for photos, favorites, the shorter home page and number commas."""

import pytest

import backfill_images
import db
import importer
from app import create_app


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    return create_app(db_path=db_path).test_client()


@pytest.fixture(autouse=True)
def ready_db(db_path):
    db.init_db(db_path)


def add(db_path, name, **extra):
    return db.create_recipe(name, 2, [{"amount": "1", "unit": "", "name": "egg"}], "Cook.",
                            [], db_path=db_path, **extra)


# --- commas in amounts ---
@pytest.mark.parametrize("line, amount, unit, name", [
    ("1,5 kg potatoes", "1 1/2", "kg", "potatoes"),
    ("0,5 l milk", "1/2", "l", "milk"),
    ("1,000 g flour", "1000", "g", "flour"),
    ("2 cups flour, sifted", "2", "cup", "flour, sifted"),
    ("2, 3 eggs", "", "", "2, 3 eggs"),   # a list comma is left alone
])
def test_commas_in_amounts(line, amount, unit, name):
    assert importer.parse_ingredient_line(line) == {"amount": amount, "unit": unit, "name": name}


# --- photos ---
def test_image_round_trips_through_json_and_database(db_path):
    recipes, errors = importer.parse_json_text(
        '{"name": "Soup", "servings": 2, "ingredients": ["1 cup water"], "steps": ["Boil"],'
        ' "image": "https://example.com/a.jpg", "source_url": "https://example.com/soup"}')
    assert not errors
    ids, _ = importer.save_recipes(recipes, db_path=db_path)
    saved = db.get_recipe(ids[0], db_path=db_path)
    assert saved["image"] == "https://example.com/a.jpg"
    assert importer.to_json_format(saved)["source_url"] == "https://example.com/soup"


def test_non_web_image_links_are_dropped():
    recipe, _ = importer.validate_recipe({"name": "x", "servings": 1, "ingredients": [], "steps": [],
                                          "image": "javascript:alert(1)"})
    assert "image" not in recipe


def test_edit_form_keeps_photo_unless_changed(db_path):
    rid = add(db_path, "Toast", image="https://example.com/t.jpg")
    db.update_recipe(rid, "Toast", 2, [], "Cook.", [], db_path=db_path)   # image=None: keep
    assert db.get_recipe(rid, db_path=db_path)["image"] == "https://example.com/t.jpg"
    db.update_recipe(rid, "Toast", 2, [], "Cook.", [], image="", db_path=db_path)
    assert db.get_recipe(rid, db_path=db_path)["image"] == ""


def test_card_shows_photo(client, db_path):
    add(db_path, "Pictured Pie", image="https://example.com/pie.jpg")
    assert "https://example.com/pie.jpg" in client.get("/?q=Pictured").get_data(as_text=True)


# --- favorites and the short home page ---
def test_star_toggles(client, db_path):
    rid = add(db_path, "Starry Stew")
    client.post(f"/favorite/{rid}", data={"next": "/"})
    assert db.get_recipe(rid, db_path=db_path)["favorite"] == 1
    client.post(f"/favorite/{rid}", data={"next": "/"})
    assert db.get_recipe(rid, db_path=db_path)["favorite"] == 0


def test_home_shows_only_favorites_when_there_are_some(client, db_path):
    liked = add(db_path, "Zz Liked Dish")
    add(db_path, "Zz Other Dish")
    db.set_favorite(liked, True, db_path=db_path)
    page = client.get("/").get_data(as_text=True)
    assert "Zz Liked Dish" in page and "Zz Other Dish" not in page
    assert "Zz Other Dish" in client.get("/?all=1").get_data(as_text=True)
    assert "Zz Other Dish" in client.get("/?q=Zz+Other").get_data(as_text=True)   # search sees everything


def test_home_shows_newest_eight_without_favorites(client, db_path):
    for n in range(12):
        add(db_path, f"Batch Dish {n:02d}")
    page = client.get("/").get_data(as_text=True)
    assert "Batch Dish 11" in page and "Batch Dish 00" not in page
    assert "Batch Dish 00" in client.get("/?all=1").get_data(as_text=True)


# --- backfill ---
def test_backfill_uses_saved_link_and_skips_handmade(db_path):
    db.init_db(db_path)
    linked = add(db_path, "Linked", source_url="https://example.com/linked")
    handmade = add(db_path, "Handmade")
    updated, no_page = backfill_images.backfill(db_path, find_image=lambda url: "https://example.com/p.jpg")
    assert (updated, no_page) == (1, 1)
    assert db.get_recipe(linked, db_path=db_path)["image"] == "https://example.com/p.jpg"
    assert db.get_recipe(handmade, db_path=db_path)["image"] == ""
