"""Basic checks that the app starts and the database is set up."""

import db
from app import create_app


def test_home_page_loads(tmp_path):
    # tmp_path is a temporary folder pytest gives us, so tests never touch the real database
    app = create_app(db_path=tmp_path / "test.db")
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"My Recipes" in response.data


def test_tables_are_created(tmp_path):
    db_path = tmp_path / "test.db"
    create_app(db_path=db_path)

    conn = db.get_connection(db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    conn.close()
    table_names = {row["name"] for row in rows}

    assert {"recipes", "ingredients", "tags", "recipe_tags"} <= table_names
