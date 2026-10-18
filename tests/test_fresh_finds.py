"""Tests for Fresh finds: reading feeds, refreshing when stale, the home page
strip, Import and Dismiss. No real network calls: feeds and recipe pages
are faked, and conftest.py switches the internet off for every test."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import db
import importer
import suggestions
from app import create_app

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    # create_app also makes the tables and imports the 4 seed recipes
    return create_app(db_path=db_path).test_client()


def rss(*items):
    """A small RSS feed. Each item is (title, link) or (title, link, extra XML)."""
    parts = []
    for item in items:
        title, link, extra = (item + ("",))[:3]
        parts.append(f"<item><title>{title}</title><link>{link}</link>{extra}</item>")
    return (
        '<?xml version="1.0"?>'
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"'
        ' xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel><title>Blog</title>" + "".join(parts) + "</channel></rss>"
    ).encode("utf-8")


def fake_fetch(feeds):
    """A stand-in for suggestions.fetch_feed: {feed url: bytes, or an exception}.
    Feeds not listed fail, like a site that's down. Remembers what was asked."""
    def fetch(url):
        fetch.calls.append(url)
        result = feeds.get(url, suggestions.FeedError("down"))
        if isinstance(result, Exception):
            raise result
        return result
    fetch.calls = []
    return fetch


@pytest.fixture
def two_feeds(monkeypatch):
    """Use two made-up feeds instead of the real list."""
    monkeypatch.setattr(suggestions, "FEEDS", [
        ("Site A", "https://a.example/feed"),
        ("Site B", "https://b.example/feed"),
    ])


def add(db_path, *titles, when=NOW, source="Site A"):
    items = [{"title": t, "url": f"https://a.example/{t.lower().replace(' ', '-')}",
              "source": source, "image": ""} for t in titles]
    return db.add_suggestions(items, suggestions.now_text(when), db_path=db_path)


def page(client, url="/"):
    return client.get(url).get_data(as_text=True)


def strip(html):
    """Just the Fresh finds part of the home page."""
    start = html.index('id="fresh-finds"')
    return html[start:html.index("</section>", start)]


# --- Reading feeds ---

def test_parse_rss_titles_links_and_images():
    raw = rss(
        ("Jo&amp;#8217;s  Chili", "https://a.example/chili/?utm_source=rss&amp;utm_medium=rss",
         '<media:content url="https://a.example/chili.jpg" medium="image"/>'),
        ("Lentil Soup", "https://a.example/soup/",
         '<content:encoded><![CDATA[<p><img src="https://a.example/soup.jpg" /></p>]]></content:encoded>'),
        ("No Picture", "https://a.example/plain/"),
    )

    found = suggestions.parse_feed(raw, "Site A")

    assert found == [
        {"title": "Jo’s Chili", "url": "https://a.example/chili/", "source": "Site A",
         "image": "https://a.example/chili.jpg"},
        {"title": "Lentil Soup", "url": "https://a.example/soup/", "source": "Site A",
         "image": "https://a.example/soup.jpg"},
        {"title": "No Picture", "url": "https://a.example/plain/", "source": "Site A", "image": ""},
    ]


def test_parse_atom_feed():
    raw = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Tofu Stir Fry</title>
        <link rel="alternate" href="https://b.example/tofu"/>
        <content type="html">&lt;img src="https://b.example/tofu.jpg"&gt;</content>
      </entry>
    </feed>"""

    assert suggestions.parse_feed(raw, "Site B") == [
        {"title": "Tofu Stir Fry", "url": "https://b.example/tofu", "source": "Site B",
         "image": "https://b.example/tofu.jpg"},
    ]


def test_parse_skips_items_without_title_or_web_link():
    raw = rss(("", "https://a.example/x"), ("Bad link", "javascript:alert(1)"), ("Good", "https://a.example/g"))
    assert [s["title"] for s in suggestions.parse_feed(raw, "A")] == ["Good"]


@pytest.mark.parametrize("title, skipped", [
    ("25 Fall Dessert Recipes", True),
    ("7 Day High Protein Diet Meal Plan", True),
    ("459: Nine Favorite Things.", True),
    ("Love & Lemons Cookbook is out now!", True),
    ("Weekly Round-Up", True),
    ("Lentil Curry", False),
    ("3 Ingredient Peanut Butter Cookies", False),
    ("Recipe-Box Chili", False),   # "recipe" on its own is fine
])
def test_roundup_posts_are_skipped(title, skipped):
    assert suggestions.looks_like_roundup(title) is skipped
    raw = rss((title.replace("&", "&amp;"), "https://a.example/post"))
    assert (suggestions.parse_feed(raw, "A") == []) is skipped


def test_parse_keeps_only_newest_few(monkeypatch):
    monkeypatch.setattr(suggestions, "MAX_PER_FEED", 2)
    raw = rss(("One", "https://a.example/1"), ("Two", "https://a.example/2"), ("Three", "https://a.example/3"))
    assert len(suggestions.parse_feed(raw, "A")) == 2


def test_parse_garbage_raises_feed_error():
    with pytest.raises(suggestions.FeedError):
        suggestions.parse_feed(b"<html>not a feed", "A")


def test_clean_url_drops_tracking_and_rejects_non_web_links():
    assert suggestions.clean_url(" https://a.example/x?utm_source=rss&id=3#top ") == "https://a.example/x?id=3"
    assert suggestions.clean_url("ftp://a.example/x") is None
    assert suggestions.clean_url("") is None


def test_image_must_be_a_web_link():
    raw = rss(("Pie", "https://a.example/pie", '<media:content url="data:image/png;base64,xx" medium="image"/>'))
    assert suggestions.parse_feed(raw, "A")[0]["image"] == ""


def test_real_feed_list_is_filled_in():
    assert len(suggestions.FEEDS) >= 5
    for name, url in suggestions.FEEDS:
        assert name and url.startswith("https://")


# --- Refresh only when stale ---

def test_stale_when_there_are_no_suggestions(client, db_path):
    assert suggestions.is_stale(db_path, NOW)


def test_stale_only_after_a_week(client, db_path):
    add(db_path, "Chili", when=NOW - timedelta(days=6))
    assert not suggestions.is_stale(db_path, NOW)
    assert suggestions.is_stale(db_path, NOW + timedelta(days=2))


def test_refresh_runs_when_there_are_none(client, db_path, two_feeds):
    fetch = fake_fetch({"https://a.example/feed": rss(("Chili", "https://a.example/chili"))})

    assert suggestions.refresh_if_stale(db_path, fetch, NOW) is True

    assert sorted(fetch.calls) == ["https://a.example/feed", "https://b.example/feed"]
    assert [s["title"] for s in db.new_suggestions(db_path=db_path)] == ["Chili"]


def test_no_refresh_when_fresh(client, db_path, two_feeds):
    add(db_path, "Chili", when=NOW - timedelta(days=1))
    fetch = fake_fetch({})

    assert suggestions.refresh_if_stale(db_path, fetch, NOW) is False
    assert fetch.calls == []


def test_refresh_when_newest_is_over_a_week_old(client, db_path, two_feeds):
    add(db_path, "Old One", when=NOW - timedelta(days=8))
    fetch = fake_fetch({"https://a.example/feed": rss(("New One", "https://a.example/new"))})

    assert suggestions.refresh_if_stale(db_path, fetch, NOW) is True
    assert db.new_suggestions(db_path=db_path)[0]["title"] == "New One"   # newest first


def test_dismissed_and_imported_count_towards_fresh(client, db_path, two_feeds):
    add(db_path, "Chili", when=NOW - timedelta(days=1))
    db.set_suggestion_status(1, "dismissed", db_path=db_path)
    assert suggestions.refresh_if_stale(db_path, fake_fetch({}), NOW) is False


def test_waits_an_hour_before_trying_again(client, db_path, two_feeds):
    fetch = fake_fetch({})   # everything is down: nothing gets added

    assert suggestions.refresh_if_stale(db_path, fetch, NOW) is True
    assert suggestions.refresh_if_stale(db_path, fetch, NOW + timedelta(minutes=30)) is False
    assert suggestions.refresh_if_stale(db_path, fetch, NOW + timedelta(minutes=61)) is True
    assert len(fetch.calls) == 4   # 2 feeds x 2 tries


def test_home_page_starts_a_refresh(db_path, two_feeds, monkeypatch):
    fetch = fake_fetch({"https://a.example/feed": rss(("Chili", "https://a.example/chili"))})
    monkeypatch.setattr(suggestions, "fetch_feed", fetch)
    client = create_app(db_path=db_path).test_client()

    html = page(client)

    assert fetch.calls
    assert "Chili" in strip(html)


def test_refresh_in_background_does_not_hold_up_the_caller(client, db_path, two_feeds, monkeypatch):
    import threading
    release = threading.Event()

    def slow_fetch(url):
        release.wait(5)
        return rss(("Chili", "https://a.example/chili"))

    monkeypatch.setattr(suggestions, "RUN_IN_BACKGROUND", True)
    started = datetime.now()
    assert suggestions.refresh_if_stale(db_path, slow_fetch, NOW) is True
    assert (datetime.now() - started).total_seconds() < 1
    assert suggestions.is_refreshing(db_path)
    release.set()


# --- Duplicates ---

def test_same_posts_are_not_added_twice(client, db_path, two_feeds):
    feed = rss(("Chili", "https://a.example/chili"), ("Soup", "https://a.example/soup"))
    fetch = fake_fetch({"https://a.example/feed": feed})

    assert suggestions.refresh(db_path, fetch, NOW) == 2
    assert suggestions.refresh(db_path, fetch, NOW + timedelta(days=8)) == 0
    assert len(db.new_suggestions(10, db_path=db_path)) == 2


def test_tracking_links_count_as_the_same_post(client, db_path, two_feeds):
    fetch = fake_fetch({
        "https://a.example/feed": rss(("Chili", "https://a.example/chili")),
        "https://b.example/feed": rss(("Chili", "https://a.example/chili?utm_source=b")),
    })
    assert suggestions.refresh(db_path, fetch, NOW) == 1


def test_dismissed_and_imported_never_come_back(client, db_path, two_feeds):
    add(db_path, "Chili", "Soup")
    db.set_suggestion_status(1, "dismissed", db_path=db_path)
    db.set_suggestion_status(2, "imported", db_path=db_path)
    fetch = fake_fetch({"https://a.example/feed": rss(("Chili", "https://a.example/chili"),
                                                      ("Soup", "https://a.example/soup"))})

    assert suggestions.refresh(db_path, fetch, NOW + timedelta(days=8)) == 0
    assert db.new_suggestions(db_path=db_path) == []


def test_posts_named_like_a_recipe_you_have_are_skipped(client, db_path, two_feeds):
    # "Chicken Stroganoff" is one of the seed recipes
    fetch = fake_fetch({"https://a.example/feed": rss(("chicken  stroganoff", "https://a.example/s"),
                                                      ("Soup", "https://a.example/soup"))})
    suggestions.refresh(db_path, fetch, NOW)
    assert [s["title"] for s in db.new_suggestions(db_path=db_path)] == ["Soup"]


def test_cards_mix_sites(client, db_path, two_feeds):
    fetch = fake_fetch({
        "https://a.example/feed": rss(("A1", "https://a.example/1"), ("A2", "https://a.example/2")),
        "https://b.example/feed": rss(("B1", "https://b.example/1"), ("B2", "https://b.example/2")),
    })
    suggestions.refresh(db_path, fetch, NOW)
    assert [s["title"] for s in db.new_suggestions(4, db_path=db_path)] == ["A1", "B1", "A2", "B2"]


# --- A failed fetch never breaks anything ---

def test_one_broken_feed_does_not_stop_the_others(client, db_path, two_feeds):
    fetch = fake_fetch({
        "https://a.example/feed": TimeoutError("too slow"),
        "https://b.example/feed": rss(("Soup", "https://b.example/soup")),
    })
    assert suggestions.refresh(db_path, fetch, NOW) == 1


def test_garbled_feed_is_skipped(client, db_path, two_feeds):
    fetch = fake_fetch({"https://a.example/feed": b"<<<not xml"})
    assert suggestions.refresh(db_path, fetch, NOW) == 0


def test_offline_home_page_still_loads(client):
    # conftest.py has the internet switched off, so every feed fails
    response = client.get("/")
    assert response.status_code == 200
    assert "My Recipes" in response.get_data(as_text=True)


def test_offline_shows_the_old_suggestions(client, db_path):
    add(db_path, "Old Chili", when=NOW - timedelta(days=30))
    assert "Old Chili" in strip(page(client))


def test_fetch_feed_turns_any_problem_into_feed_error():
    # The real download function, with the internet switched off by conftest.py
    with pytest.raises(suggestions.FeedError):
        suggestions.fetch_feed("https://a.example/feed")


def test_refresh_crash_does_not_break_home_page(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(suggestions, "refresh_if_stale", broken)
    assert client.get("/").status_code == 200


# --- The strip on the home page ---

def test_strip_shows_three_newest(client, db_path):
    add(db_path, "One", "Two", "Three", "Four")
    html = strip(page(client))

    assert "Fresh finds" in html
    assert html.count('class="find-card"') == 3
    assert "Four" not in html
    assert "Site A" in html
    assert html.count(">Import</button>") == 3
    assert html.count(">Dismiss</button>") == 3


def test_strip_shows_picture_when_there_is_one(client, db_path):
    db.add_suggestions([{"title": "Pie", "url": "https://a.example/pie", "source": "A",
                         "image": "https://a.example/pie.jpg"}], suggestions.now_text(NOW), db_path=db_path)
    assert 'src="https://a.example/pie.jpg"' in strip(page(client))


def test_strip_is_hidden_when_empty_and_while_filtering(client, db_path):
    assert "Fresh finds" not in strip(page(client))
    add(db_path, "Chili")
    assert "Chili" not in strip(page(client, "/?q=chicken"))


def test_strip_alone_for_the_page_script(client, db_path):
    add(db_path, "Chili")
    html = page(client, "/fresh-finds")
    assert "Chili" in html and "<html" not in html


# --- Dismiss ---

def test_dismiss_swaps_in_the_next_one(client, db_path):
    add(db_path, "One", "Two", "Three", "Four")

    response = client.post("/fresh-finds/1/dismiss")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#fresh-finds")
    assert db.get_suggestion(1, db_path=db_path)["status"] == "dismissed"
    html = strip(page(client))
    assert "One" not in html
    assert "Four" in html


def test_dismiss_unknown_suggestion_is_404(client):
    assert client.post("/fresh-finds/99/dismiss").status_code == 404


def test_dismiss_needs_a_post(client, db_path):
    add(db_path, "Chili")
    assert client.get("/fresh-finds/1/dismiss").status_code == 405


# --- Import ---

def recipe_page(name="Lemon Chicken Thighs"):
    """A recipe web page with the standard recipe data most blogs include."""
    data = {
        "@context": "https://schema.org", "@type": "Recipe", "name": name,
        "recipeYield": "4 servings",
        "recipeIngredient": ["2 lb chicken thighs", "1 lemon", "2 tbsp olive oil"],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Roast the chicken."}],
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


@pytest.fixture
def fake_site(monkeypatch):
    """Recipe pages come from this dict instead of the internet."""
    pages = {}
    def fetch_html(url, timeout=None):
        if url not in pages:
            raise importer.SiteUnreachable("Couldn't reach that site.")
        return pages[url]
    monkeypatch.setattr(importer, "fetch_html", fetch_html)
    return pages


def test_import_creates_a_labelled_recipe_and_opens_it(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()

    response = client.post("/fresh-finds/1/import")

    suggestion = db.get_suggestion(1, db_path=db_path)
    assert suggestion["status"] == "imported"
    recipe = db.get_recipe(suggestion["recipe_id"], db_path=db_path)
    assert recipe["name"] == "Lemon Chicken Thighs"
    assert recipe["proteins"] == ["chicken"]
    assert recipe["meal_type"] == "main"
    assert response.headers["Location"] == f"/recipes/{recipe['id']}?found=1"


def test_imported_recipe_page_has_source_and_delete(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()
    location = client.post("/fresh-finds/1/import").headers["Location"]

    html = page(client, location)

    assert "Imported from" in html and "Site A" in html
    assert "Delete this recipe" in html


def test_found_note_only_for_the_recipe_it_became(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()
    client.post("/fresh-finds/1/import")
    assert "Imported from" not in page(client, "/recipes/1?found=1")   # a seed recipe


def test_delete_button_removes_the_imported_recipe(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()
    client.post("/fresh-finds/1/import")
    recipe_id = db.get_suggestion(1, db_path=db_path)["recipe_id"]

    client.post(f"/recipes/{recipe_id}/delete")

    assert db.get_recipe(recipe_id, db_path=db_path) is None
    # It stays marked imported, so it doesn't come back
    assert db.get_suggestion(1, db_path=db_path)["status"] == "imported"


def test_imported_one_leaves_the_strip(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs", "Soup")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()
    client.post("/fresh-finds/1/import")
    html = strip(page(client))
    assert "Lemon Chicken Thighs" not in html and "Soup" in html


def test_double_click_import_saves_once(client, db_path, fake_site):
    add(db_path, "Lemon Chicken Thighs")
    fake_site["https://a.example/lemon-chicken-thighs"] = recipe_page()
    first = client.post("/fresh-finds/1/import").headers["Location"]
    before = db.count_recipes(db_path=db_path)

    second = client.post("/fresh-finds/1/import").headers["Location"]

    assert db.count_recipes(db_path=db_path) == before
    assert second == first.split("?")[0]


def test_page_without_recipe_is_dismissed_with_a_friendly_message(client, db_path, fake_site):
    add(db_path, "Nine Favorite Things")
    fake_site["https://a.example/nine-favorite-things"] = "<html><body>Just a blog post</body></html>"
    before = db.count_recipes(db_path=db_path)

    response = client.post("/fresh-finds/1/import")

    assert response.headers["Location"] == "/?find_failed=1#fresh-finds"
    assert db.get_suggestion(1, db_path=db_path)["status"] == "dismissed"
    assert db.count_recipes(db_path=db_path) == before
    html = page(client, response.headers["Location"])
    assert "couldn&#39;t read a recipe from" in html or "couldn't read a recipe from" in html
    assert "Nine Favorite Things" in html


def test_unreachable_site_keeps_the_suggestion(client, db_path, fake_site):
    add(db_path, "Chili")   # not in fake_site: like being offline

    response = client.post("/fresh-finds/1/import")

    assert response.headers["Location"] == "/?find_offline=1#fresh-finds"
    assert db.get_suggestion(1, db_path=db_path)["status"] == "new"
    assert "Check your internet" in page(client, response.headers["Location"])


def test_import_offline_with_real_download_code(client, db_path):
    # No fake site: the real importer runs with the internet switched off
    add(db_path, "Chili")
    response = client.post("/fresh-finds/1/import")
    assert "find_offline=1" in response.headers["Location"]


def test_import_unknown_suggestion_is_404(client):
    assert client.post("/fresh-finds/99/import").status_code == 404


# --- Database ---

def test_older_database_gets_the_suggestions_table(tmp_path):
    path = tmp_path / "old.db"
    db.init_db(path)
    db.create_recipe("Toast", 1, [], "Toast it.", [], db_path=path)
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE suggestions")   # like a database from before Fresh finds
    conn.commit()
    conn.close()

    client = create_app(db_path=path).test_client()

    assert client.get("/").status_code == 200
    assert db.newest_suggestion_time(db_path=path) is None
    assert [r["name"] for r in db.list_recipes(db_path=path)] == ["Toast"]


def test_status_must_be_known(client, db_path):
    add(db_path, "Chili")
    with pytest.raises(ValueError):
        db.set_suggestion_status(1, "maybe", db_path=db_path)
