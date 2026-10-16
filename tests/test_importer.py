"""Tests for importer.py: the ingredient-line parser, JSON checking,
duplicates, and turning a web page into a recipe (with no real network calls)."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

import db
import importer
from importer import ImportFailed, parse_ingredient_line, parse_json_text


# ---------------------------------------------------------------------------
# Ingredient-line parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line, amount, unit, name", [
    # The example from the roadmap
    ("1 1/2 cups flour, sifted", "1 1/2", "cup", "flour, sifted"),
    # Plain numbers, fractions and decimals
    ("2 tbsp butter", "2", "tbsp", "butter"),
    ("1/2 tsp salt", "1/2", "tsp", "salt"),
    ("0.5 cup sugar", "1/2", "cup", "sugar"),          # exact decimal -> fraction
    ("0.33 cup milk", "0.33", "cup", "milk"),          # not exact: left as written
    ("1.5 lb chicken", "1 1/2", "lb", "chicken"),
    # Unit spellings from units.py, any capitals, with or without a full stop
    ("3 Tbsp. olive oil", "3", "tbsp", "olive oil"),
    ("2 Tablespoons honey", "2", "tbsp", "honey"),
    ("1 teaspoon vanilla", "1", "tsp", "vanilla"),
    ("1 lb. ground beef", "1", "lb", "ground beef"),
    ("4 ounces cheddar", "4", "oz", "cheddar"),
    ("10 grams yeast", "10", "g", "yeast"),
    ("1 kg potatoes", "1", "kg", "potatoes"),
    ("250 ml stock", "250", "ml", "stock"),
    ("1 L water", "1", "l", "water"),
    ("2 c sugar", "2", "cup", "sugar"),
    ("2 fl. oz. cream", "2", "fl oz", "cream"),
    ("2 fluid ounces lime juice", "2", "fl oz", "lime juice"),
    # Number stuck to the unit
    ("200g butter", "200", "g", "butter"),
    ("500ml milk", "500", "ml", "milk"),
    # "of" after the unit is dropped
    ("2 cups of flour", "2", "cup", "flour"),
    # Unicode fractions
    ("½ teaspoon salt", "1/2", "tsp", "salt"),
    ("1½ cups milk", "1 1/2", "cup", "milk"),
    ("1 ½ cups milk", "1 1/2", "cup", "milk"),
    ("1⁄4 cup oil", "1/4", "cup", "oil"),               # "fraction slash" character
    # Ranges are kept as text (they aren't scaled)
    ("1-2 tbsp oil", "1-2", "tbsp", "oil"),
    ("2 to 3 cloves garlic", "2-3", "", "cloves garlic"),
    ("1 – 2 cups broth", "1-2", "cup", "broth"),
    # Counts: no unit, the rest is the name
    ("2 large eggs", "2", "", "large eggs"),
    ("3 eggs", "3", "", "eggs"),
    ("1 (14 oz) can diced tomatoes", "1", "", "(14 oz) can diced tomatoes"),
    # Words that start like a unit are NOT units
    ("2 cloves garlic", "2", "", "cloves garlic"),
    ("2 large onions", "2", "", "large onions"),
    ("1 green pepper", "1", "", "green pepper"),
    # Bullets and messy spacing
    ("- 1 cup rice", "1", "cup", "rice"),
    ("•  2   tbsp   soy sauce ", "2", "tbsp", "soy sauce"),
])
def test_parse_ingredient_line(line, amount, unit, name):
    assert parse_ingredient_line(line) == {"amount": amount, "unit": unit, "name": name}


@pytest.mark.parametrize("line", [
    "salt to taste",
    "Salt and pepper",
    "Juice of 1 lemon",
    "a pinch of nutmeg",
    "2% milk",
    "1/2-inch piece ginger",
    "1 cup",              # amount and unit but no name: keep the whole line
])
def test_lines_it_cant_split_are_kept_whole_in_the_name(line):
    assert parse_ingredient_line(line) == {"amount": "", "unit": "", "name": line}


# ---------------------------------------------------------------------------
# Pasted JSON: good input
# ---------------------------------------------------------------------------

GOOD_RECIPE = {
    "name": "Pancakes",
    "servings": 4,
    "tags": ["Breakfast", "quick"],
    "ingredients": [
        {"amount": "1 1/2", "unit": "cups", "name": "flour"},
        {"amount": "", "unit": "", "name": "salt to taste"},
    ],
    "steps": ["Mix.", "Cook."],
}


def test_one_recipe_object():
    recipes, errors = parse_json_text(json.dumps(GOOD_RECIPE))

    assert errors == []
    assert recipes == [{
        "name": "Pancakes",
        "servings": 4,
        "ingredients": [
            {"amount": "1 1/2", "unit": "cup", "name": "flour"},   # "cups" -> "cup"
            {"amount": "", "unit": "", "name": "salt to taste"},
        ],
        "steps": "Mix.\nCook.",
        "tags": ["breakfast", "quick"],
    }]


def test_list_of_recipes():
    second = dict(GOOD_RECIPE, name="Waffles")
    recipes, errors = parse_json_text(json.dumps([GOOD_RECIPE, second]))

    assert errors == []
    assert [r["name"] for r in recipes] == ["Pancakes", "Waffles"]


def test_steps_as_one_string_and_missing_tags_are_fine():
    data = {k: v for k, v in GOOD_RECIPE.items() if k != "tags"}
    data["steps"] = "Mix.\n\nCook."

    recipes, errors = parse_json_text(json.dumps(data))

    assert errors == []
    assert recipes[0]["steps"] == "Mix.\nCook."
    assert recipes[0]["tags"] == []


def test_relaxed_values_are_accepted():
    data = dict(
        GOOD_RECIPE,
        servings="6",                                      # number as text
        tags="Dinner, quick",                              # tags as one string
        ingredients=[
            {"amount": 2, "unit": "Tablespoons", "name": "butter"},   # number amount
            {"amount": 0.5, "name": "lemon"},              # decimal, no unit key
            {"amount": None, "unit": None, "name": "salt"},
            "1 cup rice",                                  # a plain text line
            "   ",                                         # blank line: skipped
        ],
    )
    recipes, errors = parse_json_text(json.dumps(data))

    assert errors == []
    assert recipes[0]["servings"] == 6
    assert recipes[0]["tags"] == ["dinner", "quick"]
    assert recipes[0]["ingredients"] == [
        {"amount": "2", "unit": "tbsp", "name": "butter"},
        {"amount": "1/2", "unit": "", "name": "lemon"},
        {"amount": "", "unit": "", "name": "salt"},
        {"amount": "1", "unit": "cup", "name": "rice"},
    ]


def test_code_fences_around_the_json_are_ignored():
    text = "```json\n" + json.dumps(GOOD_RECIPE) + "\n```"
    recipes, errors = parse_json_text(text)

    assert errors == []
    assert recipes[0]["name"] == "Pancakes"


def test_seed_file_imports_cleanly():
    # recipes.json is "our format", so all of it must pass
    text = Path(db.SEED_PATH).read_text(encoding="utf-8")
    recipes, errors = parse_json_text(text)

    assert errors == []
    assert len(recipes) == len(json.loads(text))


def test_json_format_round_trip():
    recipes, _ = parse_json_text(json.dumps(GOOD_RECIPE))
    again, errors = parse_json_text(importer.recipes_to_json(recipes))

    assert errors == []
    assert again == recipes


# ---------------------------------------------------------------------------
# Pasted JSON: bad and partial input (clear messages, never a crash)
# ---------------------------------------------------------------------------

def without(key, recipe=GOOD_RECIPE):
    return {k: v for k, v in recipe.items() if k != key}


@pytest.mark.parametrize("text, message", [
    ("", "Paste some JSON first."),
    ("   ", "Paste some JSON first."),
    ("[]", "The list is empty: there are no recipes in it."),
    ('"just text"', "The JSON should be one recipe { ... } or a list of recipes [ ... ]."),
    ("42", "The JSON should be one recipe { ... } or a list of recipes [ ... ]."),
    ("[1]", "Recipe 1: should be an object"),
])
def test_wrong_shape(text, message):
    recipes, errors = parse_json_text(text)

    assert recipes == []
    assert errors[0].startswith(message)


def test_invalid_json_says_where():
    recipes, errors = parse_json_text('{"name": "Toast",\n "servings": }')

    assert recipes == []
    assert errors[0].startswith("That isn't valid JSON (line 2, column")


def test_very_deep_json_does_not_crash():
    recipes, errors = parse_json_text("[" * 100000 + "]" * 100000)

    assert recipes == []
    assert errors


def test_missing_servings_in_recipe_2():
    recipes, errors = parse_json_text(json.dumps([GOOD_RECIPE, without("servings")]))

    assert recipes == []   # nothing is saved if any part is wrong
    assert errors == ["Recipe 2 (\"Pancakes\"): missing 'servings'"]


def test_missing_name_has_no_name_in_the_label():
    _, errors = parse_json_text(json.dumps(without("name")))

    assert errors == ["Recipe 1: missing 'name'"]


@pytest.mark.parametrize("key", ["name", "servings", "ingredients", "steps"])
def test_each_required_field(key):
    _, errors = parse_json_text(json.dumps(without(key)))

    assert any(f"missing '{key}'" in e for e in errors)


@pytest.mark.parametrize("changes, message", [
    ({"name": "  "}, "'name' should be some text"),
    ({"name": 5}, "'name' should be some text"),
    ({"servings": 0}, "'servings' should be a whole number"),
    ({"servings": -2}, "'servings' should be a whole number"),
    ({"servings": 2.5}, "'servings' should be a whole number"),
    ({"servings": "four"}, "'servings' should be a whole number"),
    ({"servings": True}, "'servings' should be a whole number"),
    ({"ingredients": "flour"}, "'ingredients' should be a list"),
    ({"ingredients": [{"amount": "1"}]}, "ingredient 1: missing 'name'"),
    ({"ingredients": [{"name": ""}]}, "ingredient 1: 'name' should be some text"),
    ({"ingredients": [{"name": "x", "amount": ["1"]}]}, "ingredient 1: 'amount' should be text"),
    ({"ingredients": [{"name": "x"}, 7]}, "ingredient 2: should be an object"),
    ({"steps": 3}, "'steps' should be a list of text"),
    ({"steps": ["ok", 2]}, "'steps' should be a list of text"),
    ({"tags": {"a": 1}}, "'tags' should be a list of text"),
])
def test_bad_values(changes, message):
    recipes, errors = parse_json_text(json.dumps(dict(GOOD_RECIPE, **changes)))

    assert recipes == []
    assert any(message in e for e in errors), errors


def test_all_problems_are_listed_at_once():
    _, errors = parse_json_text(json.dumps({"name": "X", "servings": 0}))

    assert errors == [
        "Recipe 1 (\"X\"): 'servings' should be a whole number, 1 or more",
        "Recipe 1 (\"X\"): missing 'ingredients'",
        "Recipe 1 (\"X\"): missing 'steps'",
    ]


def test_long_error_lists_are_cut_short():
    _, errors = parse_json_text(json.dumps([{}] * 30))

    assert len(errors) == importer.MAX_ERRORS + 1
    assert errors[-1].startswith("...and ")


# ---------------------------------------------------------------------------
# Duplicates and saving
# ---------------------------------------------------------------------------

def named(*names):
    return [dict(name=n, servings=2, ingredients=[], steps="", tags=[]) for n in names]


def test_find_duplicates_ignores_capitals_and_spaces():
    recipes = named("Pancakes", "  chicken   STROGANOFF", "New one")

    assert importer.find_duplicates(recipes, ["Chicken Stroganoff", "pancakes"]) == {0, 1}


def test_find_duplicates_within_the_same_import():
    assert importer.find_duplicates(named("Soup", "Salad", "soup"), []) == {2}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    db.create_recipe("Pancakes", 2, [], "", [], db_path=path)
    return path


def test_save_skips_duplicates_by_default(db_path):
    saved, skipped = importer.save_recipes(named("Pancakes", "Waffles"), db_path=db_path)

    assert len(saved) == 1
    assert skipped == ["Pancakes"]
    assert [r["name"] for r in db.list_recipes(db_path=db_path)] == ["Pancakes", "Waffles"]


def test_save_anyway_saves_the_duplicate(db_path):
    saved, skipped = importer.save_recipes(named("Pancakes", "Waffles"), save_anyway={0}, db_path=db_path)

    assert len(saved) == 2
    assert skipped == []
    assert [r["name"] for r in db.list_recipes(db_path=db_path)] == ["Pancakes", "Pancakes", "Waffles"]


# ---------------------------------------------------------------------------
# The prompt for Claude
# ---------------------------------------------------------------------------

def test_prompt_doc_matches_the_app():
    doc = (Path(__file__).parent.parent / "docs" / "import-prompt.md").read_text(encoding="utf-8")

    assert importer.CLAUDE_PROMPT.strip() in doc.replace("\r\n", "\n")


def test_prompt_example_is_valid_for_our_importer():
    # The example in the prompt must pass our own checks
    start = importer.CLAUDE_PROMPT.index("\n{")   # the example starts on its own line
    end = importer.CLAUDE_PROMPT.rindex("}") + 1
    recipes, errors = parse_json_text(importer.CLAUDE_PROMPT[start:end])

    assert errors == []
    assert recipes[0]["name"] == "Garlic Butter Pasta"


# ---------------------------------------------------------------------------
# Import from a link (network and scraper are faked)
# ---------------------------------------------------------------------------

class FakeScraper:
    """Stands in for a recipe-scrapers result. Fields set to an Exception raise it."""

    def __init__(self, **fields):
        self.fields = {
            "title": "Banana Bread",
            "yields": "8 servings",
            "ingredients": ["3 ripe bananas", "1 1/2 cups flour, sifted", "salt to taste", ""],
            "instructions_list": ["Mash bananas.", "Mix and bake."],
            "instructions": "Mash bananas.\nMix and bake.",
        }
        self.fields.update(fields)

    def __getattr__(self, field):
        def method():
            value = self.fields[field]
            if isinstance(value, Exception):
                raise value
            return value
        return method


def test_recipe_from_scraper():
    recipe, notes = importer.recipe_from_scraper(FakeScraper())

    assert recipe == {
        "name": "Banana Bread",
        "servings": 8,
        "ingredients": [
            {"amount": "3", "unit": "", "name": "ripe bananas"},
            {"amount": "1 1/2", "unit": "cup", "name": "flour, sifted"},
            {"amount": "", "unit": "", "name": "salt to taste"},   # kept, not dropped
        ],
        "steps": "Mash bananas.\nMix and bake.",
        "tags": [],
    }
    assert notes == ["1 ingredient line(s) had no amount we could read; they're kept whole in the name."]


def test_missing_fields_from_the_page():
    scraper = FakeScraper(yields=ValueError("no yields"), instructions_list=ValueError("x"), instructions="")

    recipe, notes = importer.recipe_from_scraper(scraper)

    assert recipe["servings"] == importer.DEFAULT_SERVINGS
    assert recipe["steps"] == ""
    assert any("servings" in n for n in notes)
    assert any("No steps" in n for n in notes)


def test_falls_back_to_standard_recipe_data_when_site_scraper_breaks():
    # Like Simply Recipes in Oct 2026: its own scraper failed on steps, but
    # the schema.org data on the page still had them
    broken = AttributeError("'NoneType' object has no attribute 'ol'")
    scraper = FakeScraper(instructions_list=broken, instructions=broken)
    scraper.schema = FakeScraper(instructions_list=[], instructions="Step one.\nStep two.")

    recipe, notes = importer.recipe_from_scraper(scraper)

    assert recipe["steps"] == "Step one.\nStep two."
    assert not any("No steps" in n for n in notes)


def test_falls_back_to_instructions_text():
    recipe, _ = importer.recipe_from_scraper(FakeScraper(instructions_list=[]))

    assert recipe["steps"] == "Mash bananas.\nMix and bake."


@pytest.mark.parametrize("fields", [{"title": ""}, {"ingredients": []}, {"title": ValueError("none")}])
def test_page_without_a_recipe(fields):
    with pytest.raises(ImportFailed, match="Couldn't find a recipe"):
        importer.recipe_from_scraper(FakeScraper(**fields))


@pytest.mark.parametrize("url", ["", "example.com/recipe", "ftp://example.com/r", "file:///C:/secret.txt",
                                 "javascript:alert(1)", "http://"])
def test_only_http_and_https_links(url, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("should not try to download")
    monkeypatch.setattr(importer.urllib.request, "urlopen", no_network)

    with pytest.raises(ImportFailed, match="start with http"):
        importer.recipe_from_url(url)


class FakeResponse(io.BytesIO):
    def __init__(self, body, url="https://example.com/r", charset="utf-8"):
        super().__init__(body)
        self.url = url
        self.headers = type("Headers", (), {"get_content_charset": lambda self: charset})()

    def geturl(self):
        return self.url


def test_fetch_html_uses_a_timeout(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append((request.full_url, timeout))
        return FakeResponse("<p>café</p>".encode("utf-8"))
    monkeypatch.setattr(importer.urllib.request, "urlopen", fake_urlopen)

    assert importer.fetch_html("https://example.com/r") == "<p>café</p>"
    assert calls == [("https://example.com/r", importer.URL_TIMEOUT)]


def test_fetch_html_unknown_charset_falls_back_to_utf8(monkeypatch):
    monkeypatch.setattr(importer.urllib.request, "urlopen",
                        lambda request, timeout=None: FakeResponse(b"ok", charset="made-up"))

    assert importer.fetch_html("https://example.com/r") == "ok"


def test_fetch_html_refuses_huge_pages(monkeypatch):
    monkeypatch.setattr(importer, "MAX_PAGE_BYTES", 10)
    monkeypatch.setattr(importer.urllib.request, "urlopen",
                        lambda request, timeout=None: FakeResponse(b"x" * 11))

    with pytest.raises(ImportFailed, match="too big"):
        importer.fetch_html("https://example.com/r")


@pytest.mark.parametrize("error, message", [
    (urllib.error.URLError("no internet"), "Couldn't reach that site"),
    (TimeoutError(), "Couldn't reach that site"),
    (urllib.error.HTTPError("u", 404, "Not Found", {}, None), "wasn't found"),
    (urllib.error.HTTPError("u", 403, "Forbidden", {}, None), "blocked"),
    (urllib.error.HTTPError("u", 500, "Oops", {}, None), r"error \(500\)"),
    (ValueError("bad url"), "Couldn't read that link"),
])
def test_fetch_html_failures_are_friendly(error, message, monkeypatch):
    def fail(request, timeout=None):
        raise error
    monkeypatch.setattr(importer.urllib.request, "urlopen", fail)

    with pytest.raises(ImportFailed, match=message):
        importer.fetch_html("https://example.com/r")


def test_recipe_from_url_uses_the_scraper(monkeypatch):
    seen = {}

    def fake_scrape(html, org_url, supported_only):
        seen.update(html=html, url=org_url, supported_only=supported_only)
        return FakeScraper()
    monkeypatch.setattr(importer, "fetch_html", lambda url: "<html>page</html>")
    monkeypatch.setattr(importer, "scrape_html", fake_scrape)

    recipe, _ = importer.recipe_from_url("  https://example.com/bread  ")

    assert recipe["name"] == "Banana Bread"
    assert seen == {"html": "<html>page</html>", "url": "https://example.com/bread", "supported_only": False}


def test_unsupported_site(monkeypatch):
    from recipe_scrapers._exceptions import NoSchemaFoundInWildMode

    def fake_scrape(html, org_url, supported_only):
        raise NoSchemaFoundInWildMode(org_url)
    monkeypatch.setattr(importer, "fetch_html", lambda url: "<html></html>")
    monkeypatch.setattr(importer, "scrape_html", fake_scrape)

    with pytest.raises(ImportFailed, match="may not be supported"):
        importer.recipe_from_url("https://example.com/not-a-recipe")


def test_real_scraper_reads_standard_recipe_data(monkeypatch):
    # A tiny page with schema.org recipe data, like most recipe blogs have.
    # Runs the real recipe-scrapers library, but on this text: no network.
    page = """<html><head><script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Recipe", "name": "Simple Rice",
     "recipeYield": "2 servings",
     "recipeIngredient": ["1 cup white rice", "2 cups water", "salt to taste"],
     "recipeInstructions": [{"@type": "HowToStep", "text": "Rinse the rice."},
                            {"@type": "HowToStep", "text": "Simmer 18 minutes."}]}
    </script></head><body></body></html>"""
    monkeypatch.setattr(importer, "fetch_html", lambda url: page)

    recipe, _ = importer.recipe_from_url("https://my-little-food-blog.example/rice")

    assert recipe["name"] == "Simple Rice"
    assert recipe["servings"] == 2
    assert recipe["ingredients"][0] == {"amount": "1", "unit": "cup", "name": "white rice"}
    assert recipe["ingredients"][2] == {"amount": "", "unit": "", "name": "salt to taste"}
    assert recipe["steps"] == "Rinse the rice.\nSimmer 18 minutes."
