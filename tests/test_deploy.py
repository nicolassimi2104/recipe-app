"""Tests for the hosted-copy features: the password gate, /export, and wsgi.py."""

import importlib
import json
from urllib.parse import unquote

import pytest

import db
import importer
from app import create_app, safe_next

PASSWORD = "correct horse battery staple"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def open_client(db_path):
    # No APP_PASSWORD (conftest.py clears it): the gate is off
    return create_app(db_path=db_path).test_client()


@pytest.fixture
def gated_client(db_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    return create_app(db_path=db_path).test_client()


def log_in(client, password=PASSWORD, next_page=""):
    return client.post("/login", data={"password": password, "next": next_page})


# --- Password gate: off ---

def test_no_password_means_no_gate(open_client):
    assert open_client.get("/").status_code == 200
    assert open_client.get("/plan").status_code == 200
    assert open_client.get("/export").status_code == 200


def test_no_password_hides_logout_and_login_goes_home(open_client):
    assert "Log out" not in open_client.get("/").get_data(as_text=True)
    response = open_client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


# --- Password gate: on ---

@pytest.mark.parametrize("path", ["/", "/plan", "/grocery?recipe=1", "/import", "/export",
                                  "/recipes/1", "/recipes/new", "/recipes/1/edit"])
def test_gate_sends_every_page_to_login(gated_client, path):
    response = gated_client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")


def test_gate_blocks_form_posts_too(gated_client, db_path):
    before = db.count_recipes(db_path=db_path)
    response = gated_client.post("/recipes/1/delete")
    assert response.status_code == 302
    assert db.count_recipes(db_path=db_path) == before


def test_gate_blocks_import_save(gated_client, db_path):
    before = db.count_recipes(db_path=db_path)
    recipe = {"name": "Sneaky", "servings": 1, "ingredients": [], "steps": []}
    gated_client.post("/import/save", data={"recipes_json": json.dumps(recipe)})
    assert db.count_recipes(db_path=db_path) == before


def test_login_page_and_css_load_without_logging_in(gated_client):
    page = gated_client.get("/login")
    assert page.status_code == 200
    assert 'type="password"' in page.get_data(as_text=True)
    assert gated_client.get("/static/style.css").status_code == 200


def test_wrong_password_is_refused(gated_client):
    response = log_in(gated_client, "wrong")
    assert response.status_code == 401
    assert "isn&#39;t right" in response.get_data(as_text=True)
    assert gated_client.get("/").status_code == 302   # still locked


def test_empty_password_is_refused(gated_client):
    assert log_in(gated_client, "").status_code == 401
    assert gated_client.get("/").status_code == 302


def test_right_password_unlocks_every_page(gated_client):
    response = log_in(gated_client)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    home = gated_client.get("/")
    assert home.status_code == 200
    assert "Log out" in home.get_data(as_text=True)
    assert gated_client.get("/plan").status_code == 200
    assert gated_client.get("/export").status_code == 200


def test_login_returns_you_to_the_page_you_wanted(gated_client):
    location = gated_client.get("/plan?recipe=1").headers["Location"]
    next_page = unquote(location.split("next=", 1)[1])

    response = log_in(gated_client, next_page=next_page)
    assert response.headers["Location"] == "/plan?recipe=1"


def test_login_never_redirects_to_another_site(gated_client):
    response = log_in(gated_client, next_page="https://evil.example/")
    assert response.headers["Location"] == "/"


@pytest.mark.parametrize("target, expected", [
    ("/plan?recipe=1", "/plan?recipe=1"),
    ("", "/"),
    (None, "/"),
    ("https://evil.example", "/"),
    ("//evil.example", "/"),
    ("/\\evil.example", "/"),
])
def test_safe_next(open_client, target, expected):
    with open_client.application.test_request_context():
        assert safe_next(target) == expected


def test_logout_locks_the_app_again(gated_client):
    log_in(gated_client)
    assert gated_client.get("/").status_code == 200

    response = gated_client.get("/logout")
    assert response.headers["Location"] == "/login"
    assert gated_client.get("/").status_code == 302


def test_login_cookie_is_long_lived_and_http_only(gated_client):
    cookie = log_in(gated_client).headers["Set-Cookie"]
    assert "Expires=" in cookie      # survives closing the browser
    assert "HttpOnly" in cookie      # page scripts can't read it
    assert "SameSite=Lax" in cookie  # other sites can't post forms as you
    assert "Secure" not in cookie    # off unless SESSION_COOKIE_SECURE=1


def test_secure_cookie_setting(db_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    client = create_app(db_path=db_path).test_client()
    assert "Secure" in log_in(client).headers["Set-Cookie"]


def test_password_without_secret_key_refuses_to_start(db_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(db_path=db_path)


def test_cookie_signed_with_another_key_does_not_work(db_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "key-one")
    first = create_app(db_path=db_path).test_client()
    log_in(first)
    cookie = first.get_cookie("session").value

    monkeypatch.setenv("SECRET_KEY", "key-two")
    second = create_app(db_path=db_path).test_client()
    second.set_cookie("session", cookie)
    assert second.get("/").status_code == 302


# --- Settings from environment variables ---

def test_db_path_comes_from_environment(tmp_path, monkeypatch):
    env_db = tmp_path / "from_env.db"
    monkeypatch.setenv("DB_PATH", str(env_db))
    app = create_app()
    assert app.config["DB_PATH"] == str(env_db)
    assert db.count_recipes(db_path=env_db) == 4   # the seed recipes went into that file


def test_wsgi_app_has_debug_off(tmp_path, monkeypatch):
    # DB_PATH set first, so importing wsgi.py never touches the real recipes.db
    monkeypatch.setenv("DB_PATH", str(tmp_path / "wsgi.db"))
    import wsgi
    wsgi = importlib.reload(wsgi)
    assert wsgi.app.debug is False
    assert wsgi.app.config["DB_PATH"] == str(tmp_path / "wsgi.db")


# --- Export ---

def test_export_downloads_all_recipes_as_json(open_client, db_path):
    response = open_client.get("/export")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="recipes-')
    data = json.loads(response.get_data(as_text=True))
    assert isinstance(data, list)
    assert len(data) == db.count_recipes(db_path=db_path)
    assert set(data[0]) == {"name", "servings", "tags", "ingredients", "steps"}
    assert isinstance(data[0]["steps"], list)


def test_export_keeps_ingredients_tags_and_special_characters(open_client, db_path):
    db.create_recipe(
        name="Crème brûlée", servings=2,
        ingredients=[{"amount": "1/3", "unit": "cup", "name": "sugar"}],
        steps="Bake at 160°C.\nTorch the top.", tags=["dessert"], db_path=db_path,
    )
    data = json.loads(open_client.get("/export").get_data(as_text=True))
    recipe = next(r for r in data if r["name"] == "Crème brûlée")

    assert recipe == {
        "name": "Crème brûlée", "servings": 2, "tags": ["dessert"],
        "ingredients": [{"amount": "1/3", "unit": "cup", "name": "sugar"}],
        "steps": ["Bake at 160°C.", "Torch the top."],
    }


def test_export_with_no_recipes_is_an_empty_list(open_client, db_path):
    for recipe in db.list_recipes(db_path=db_path):
        db.delete_recipe(recipe["id"], db_path=db_path)
    assert json.loads(open_client.get("/export").get_data(as_text=True)) == []


def test_import_page_links_to_export(open_client):
    assert 'href="/export"' in open_client.get("/import").get_data(as_text=True)


def full_recipes(db_path):
    """Every recipe with all its details (minus the database id), sorted by name."""
    recipes = [db.get_recipe(r["id"], db_path=db_path) for r in db.list_recipes(db_path=db_path)]
    return [{k: v for k, v in r.items() if k != "id"} for r in recipes]


def test_export_round_trips_through_the_importer(open_client):
    exported = open_client.get("/export").get_data(as_text=True)

    recipes, errors = importer.parse_json_text(exported)
    assert errors == []
    assert [importer.to_json_format(r) for r in recipes] == json.loads(exported)


def test_export_then_import_into_a_new_copy_gives_the_same_recipes(open_client, db_path, tmp_path):
    db.create_recipe(
        name="Toast", servings=2,
        ingredients=[{"amount": "2", "unit": "", "name": "bread"},
                     {"amount": "1 1/2", "unit": "tbsp", "name": "butter"}],
        steps="Toast.\nButter.", tags=["breakfast", "quick"], db_path=db_path,
    )
    exported = open_client.get("/export").get_data(as_text=True)

    # A fresh hosted copy starts with the 4 seed recipes; those are skipped as duplicates
    new_db = tmp_path / "hosted.db"
    hosted = create_app(db_path=new_db).test_client()
    response = hosted.post("/import/save", data={"recipes_json": exported})

    assert response.status_code == 302
    assert full_recipes(new_db) == full_recipes(db_path)
