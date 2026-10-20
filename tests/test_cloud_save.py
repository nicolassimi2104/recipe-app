"""Tests for keeping the database in Postgres on Render (cloud_save.py).

No real Postgres here: FakeStore keeps the saved copy in memory instead.
"""

import json

import pytest

import cloud_save
import db
from app import create_app


class FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.saves = 0

    def load(self):
        return self.data

    def save(self, data):
        self.data = data
        self.saves += 1


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(cloud_save, "store_from_env", lambda: fake)
    return fake


@pytest.fixture
def no_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("RESTORE_FILE", str(tmp_path / "missing.json"))


def names(db_path):
    return sorted(r["name"] for r in db.list_recipes(db_path=db_path))


def test_off_without_database_url():
    assert cloud_save.store_from_env() is None


def test_on_with_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/recipes")
    assert isinstance(cloud_save.store_from_env(), cloud_save.PostgresStore)


def test_brand_new_app_starts_with_samples_but_saves_nothing_yet(tmp_path, store, no_backup):
    create_app(db_path=tmp_path / "a.db")
    assert len(names(tmp_path / "a.db")) == 4
    assert store.data is None   # so a backup file added later still loads


def test_backup_added_after_first_start_still_loads(tmp_path, store, no_backup, monkeypatch):
    # RENDER.md order: the app starts once, then the backup is uploaded
    create_app(db_path=tmp_path / "first.db")
    monkeypatch.setenv("RESTORE_FILE", str(write_backup(tmp_path, BACKUP)))
    create_app(db_path=tmp_path / "second.db")
    assert names(tmp_path / "second.db") == ["Taco Night", "Taco Night"]


def test_restart_brings_back_changes(tmp_path, store, no_backup):
    first = tmp_path / "first.db"
    client = create_app(db_path=first).test_client()
    recipe_id = db.list_recipes(db_path=first)[0]["id"]
    client.post(f"/favorite/{recipe_id}", data={"next": "/"})

    # Render restarts: the old file is gone, the app starts on a new empty one
    second = tmp_path / "second.db"
    create_app(db_path=second)
    assert db.get_recipe(recipe_id, db_path=second)["favorite"] == 1
    assert names(second) == names(first)


def test_only_submitted_forms_save(tmp_path, store, no_backup):
    client = create_app(db_path=tmp_path / "a.db").test_client()
    after_start = store.saves
    client.get("/")
    assert store.saves == after_start
    recipe_id = db.list_recipes(db_path=tmp_path / "a.db")[0]["id"]
    client.post(f"/favorite/{recipe_id}", data={"next": "/"})
    assert store.saves == after_start + 1


def test_failed_post_does_not_save(tmp_path, store, no_backup):
    client = create_app(db_path=tmp_path / "a.db").test_client()
    after_start = store.saves
    client.post("/favorite/99999", data={"next": "/"})   # no such recipe: 404
    assert store.saves == after_start


def test_save_problem_does_not_break_the_page(tmp_path, store, no_backup):
    client = create_app(db_path=tmp_path / "a.db").test_client()

    def broken(data):
        raise OSError("Postgres is down")
    store.save = broken
    recipe_id = db.list_recipes(db_path=tmp_path / "a.db")[0]["id"]
    response = client.post(f"/favorite/{recipe_id}", data={"next": "/"})
    assert response.status_code == 302


def test_unreachable_postgres_stops_startup(tmp_path, store, no_backup):
    # Starting empty would save the samples over the good copy, so don't start
    def broken():
        raise OSError("can't connect")
    store.load = broken
    with pytest.raises(OSError):
        create_app(db_path=tmp_path / "a.db")


def write_backup(tmp_path, recipes):
    path = tmp_path / "recipes-backup.json"
    path.write_text(json.dumps(recipes), encoding="utf-8")
    return path


BACKUP = [
    {"name": "Taco Night", "servings": 4, "tags": ["dinner"],
     "ingredients": [{"amount": "1", "unit": "lb", "name": "ground beef"}],
     "steps": ["Brown the beef.", "Fill the tacos."]},
    {"name": "Taco Night", "servings": 2, "tags": [],
     "ingredients": [{"amount": "2", "unit": "", "name": "eggs"}], "steps": ["Cook."],
     "image": "https://example.com/taco.jpg"},
]


def test_empty_postgres_loads_backup_file(tmp_path, store, monkeypatch):
    monkeypatch.setenv("RESTORE_FILE", str(write_backup(tmp_path, BACKUP)))
    create_app(db_path=tmp_path / "a.db")
    # Both kept (even the same name twice), and no sample recipes added
    assert names(tmp_path / "a.db") == ["Taco Night", "Taco Night"]
    images = [db.get_recipe(r["id"], db_path=tmp_path / "a.db")["image"]
              for r in db.list_recipes(db_path=tmp_path / "a.db")]
    assert "https://example.com/taco.jpg" in images
    assert store.data   # and the restored recipes are saved to Postgres


def test_saved_copy_wins_over_backup_file(tmp_path, store, no_backup, monkeypatch):
    client = create_app(db_path=tmp_path / "first.db").test_client()
    client.post("/favorite/1", data={"next": "/"})   # a change saves the 4 samples
    monkeypatch.setenv("RESTORE_FILE", str(write_backup(tmp_path, BACKUP)))
    assert cloud_save.restore_on_startup(tmp_path / "second.db", store) == "saved copy"
    assert "Taco Night" not in names(tmp_path / "second.db")


def test_backup_not_added_to_existing_recipes(tmp_path):
    path = tmp_path / "a.db"
    db.init_db(path)
    db.import_seed_data(path)
    backup = write_backup(tmp_path, BACKUP)
    assert cloud_save.restore_on_startup(path, FakeStore(), backup_file=backup) == "nothing"
    assert "Taco Night" not in names(path)


def test_broken_backup_stops_startup(tmp_path, store, monkeypatch):
    bad = tmp_path / "recipes-backup.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("RESTORE_FILE", str(bad))
    with pytest.raises(RuntimeError, match="can't be read"):
        create_app(db_path=tmp_path / "a.db")
    assert store.data is None   # nothing was saved over Postgres


def test_nothing_anywhere(tmp_path):
    result = cloud_save.restore_on_startup(tmp_path / "a.db", FakeStore(),
                                           backup_file=tmp_path / "missing.json")
    assert result == "nothing"
