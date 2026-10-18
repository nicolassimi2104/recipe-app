"""Recipe import: read recipes from pasted JSON or from a recipe web page.

Plain functions with no Flask code, like units.py and scaling.py. The web
pages in app.py call these and show the results.

Both ways in end up with the same thing: a list of recipe dicts shaped like
db.create_recipe wants them:
    {"name": ..., "servings": 4, "ingredients": [...], "steps": "line\\nline", "tags": [...]}
"""

import codecs
import http.client
import json
import math
import re
import urllib.error
import urllib.request
from fractions import Fraction
from urllib.parse import urlparse

from recipe_scrapers import scrape_html
from recipe_scrapers._exceptions import RecipeScrapersExceptions

import db
from scaling import format_amount
from units import ALIASES, normalize_unit

# The prompt shown on the import page (with a "Copy prompt" button). The same
# text is in docs/import-prompt.md; a test checks the two stay in step.
CLAUDE_PROMPT = """\
Turn the recipe below into JSON for my recipe app.

Rules:
- Output ONLY valid JSON. No explanation before or after, no markdown, no code fences.
- Use exactly this format. For several recipes, put them in a list: [ {...}, {...} ]

{
  "name": "Garlic Butter Pasta",
  "servings": 4,
  "tags": ["dinner", "quick"],
  "ingredients": [
    {"amount": "1", "unit": "lb", "name": "spaghetti"},
    {"amount": "1 1/2", "unit": "tbsp", "name": "butter"},
    {"amount": "4", "unit": "", "name": "garlic cloves, minced"},
    {"amount": "", "unit": "", "name": "salt to taste"}
  ],
  "steps": [
    "Boil the spaghetti until al dente.",
    "Melt the butter and cook the garlic for 1 minute.",
    "Toss the pasta with the garlic butter and season."
  ]
}

- "servings" is a whole number.
- "amount" is text: a whole number or a fraction like "1/2" or "1 1/2". No decimals like 0.5 and no fraction characters like ½.
- "unit" is one of: tsp, tbsp, cup, oz, lb, g, kg, ml, l. Use "" for counts (like 3 eggs) and put other words such as "clove" or "can" in the name.
- When there is no exact amount (like "salt to taste" or "oil for frying"), leave "amount" and "unit" as "".
- Put preparation notes in the name after a comma, like "onion, diced".
- "steps" has one string per step, in order.
- "tags" has a few short lowercase tags, like dinner, breakfast, vegetarian, quick.

Recipe:
"""

# How long to wait for a recipe site before giving up, in seconds
URL_TIMEOUT = 10
# Recipe pages are rarely over 2 MB; stop reading at 5 MB so a huge file can't jam the app
MAX_PAGE_BYTES = 5 * 1024 * 1024
# Sent with the request; some sites refuse requests that don't say who they are
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (personal recipe app; recipe-scrapers)"}
# Used when a web page doesn't say how many servings it makes
DEFAULT_SERVINGS = 4
# Stop listing problems after this many, so one broken paste doesn't fill the screen
MAX_ERRORS = 20

URL_HELP = "You can still import it with option A: paste the recipe into a Claude chat with the prompt below, then paste the JSON here."


class ImportFailed(Exception):
    """A friendly message for the user when importing from a link doesn't work."""


class SiteUnreachable(ImportFailed):
    """The site couldn't be reached or had a hiccup (no internet, too slow,
    server error), so trying again later may work. Fresh finds keeps the
    suggestion in that case; for any other ImportFailed it's dismissed."""


# ---------------------------------------------------------------------------
# Ingredient lines: "1 1/2 cups flour, sifted" -> amount / unit / name
# ---------------------------------------------------------------------------

# Fraction characters some sites use, like ½. "1½" becomes "1 1/2".
UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅕": "1/5", "⅙": "1/6",
}

# The amount at the very start of a line. Tried top to bottom, so "1 1/2"
# is matched as one amount before "1" on its own gets a chance.
_NUMBER = r"\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+"     # "1 1/2", "1/2", "0.5", "2"
AMOUNT_AT_START = re.compile(
    rf"^(?P<amount>(?:{_NUMBER})(?:\s*(?:-|–|to)\s*(?:{_NUMBER}))?)"   # optional range: "2-3", "2 to 3"
    r"(?=[\s(a-zA-Z]|$)"   # then a space, letter or "(": "200g" yes, "2%" or "1/2-inch" no
)

# Longest unit spellings first, so "fluid ounces" is tried before "fluid"
_UNIT_WORDS = sorted({alias for aliases in ALIASES.values() for alias in aliases}, key=len, reverse=True)
UNIT_AT_START = re.compile(
    r"^(?P<unit>" + "|".join(re.escape(w).replace(r"\ ", r"\.?\s+") for w in _UNIT_WORDS) + r")\.?(?![a-zA-Z])",
    re.IGNORECASE,
)


def parse_ingredient_line(line):
    """Split one ingredient line into {"amount", "unit", "name"}.

    "1 1/2 cups flour, sifted" -> {"amount": "1 1/2", "unit": "cup", "name": "flour, sifted"}
    "200g butter"              -> {"amount": "200", "unit": "g", "name": "butter"}
    "2 large eggs"             -> {"amount": "2", "unit": "", "name": "large eggs"}
    "salt to taste"            -> {"amount": "", "unit": "", "name": "salt to taste"}

    Only the units in units.py count as units (tsp, cup, g...). Anything the
    parser isn't sure about stays in the name, so nothing is ever lost.
    """
    text = _clean_line(line)
    whole_line = {"amount": "", "unit": "", "name": text}

    match = AMOUNT_AT_START.match(text)
    if not match:
        return whole_line
    amount = _tidy_amount(match.group("amount"))
    rest = text[match.end():].strip()

    unit = ""
    unit_match = UNIT_AT_START.match(rest)
    if unit_match:
        unit = normalize_unit(unit_match.group("unit"))
        rest = rest[unit_match.end():].strip()
        rest = re.sub(r"^of\s+", "", rest, flags=re.IGNORECASE)   # "2 cups of flour"

    name = rest.lstrip(" ,").strip()
    if not name:
        # "1 cup" with nothing after it: keep the whole line rather than guess
        return whole_line
    return {"amount": amount, "unit": unit, "name": name}


# Trim spaces and bullets ("- ", "• "), and turn "1½" into "1 1/2"
def _clean_line(line):
    text = str(line or "")
    for symbol, fraction in UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d)\s*{symbol}", rf"\1 {fraction}", text)   # "1½" -> "1 1/2"
        text = text.replace(symbol, fraction)
    text = text.replace("⁄", "/")   # the special "fraction slash" some sites use
    text = " ".join(text.split())    # tabs, newlines and double spaces -> one space
    return text.lstrip("-•*·▢◻□ ").strip()


# "1  1/2" -> "1 1/2", "2 to 3" -> "2-3", "0.5" -> "1/2" (only when exact)
def _tidy_amount(text):
    text = " ".join(text.split())
    text = re.sub(r"\s*(?:-|–|to)\s*", "-", text)
    if re.fullmatch(r"\d*\.\d+", text):
        value = Fraction(text)
        friendly = format_amount(value)
        # Only swap when nothing is lost: 0.5 -> "1/2" yes, 0.33 -> "1/3" no
        if Fraction(sum(Fraction(part) for part in friendly.split())) == value:
            return friendly
    return text


# ---------------------------------------------------------------------------
# Pasted JSON
# ---------------------------------------------------------------------------

def parse_json_text(text):
    """Read pasted JSON for one recipe or a list of recipes.

    Returns (recipes, errors). If there are any errors, recipes is empty:
    we only save when everything in the paste makes sense.
    """
    text = _strip_code_fence((text or "").strip())
    if not text:
        return [], ["Paste some JSON first."]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"That isn't valid JSON (line {e.lineno}, column {e.colno}: {e.msg})."]
    except RecursionError:
        return [], ["That JSON is nested too deeply to be a recipe."]

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return [], ["The JSON should be one recipe { ... } or a list of recipes [ ... ]."]
    if not data:
        return [], ["The list is empty: there are no recipes in it."]

    recipes, errors = [], []
    for number, item in enumerate(data, start=1):
        recipe, problems = validate_recipe(item)
        label = f"Recipe {number}"
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            label += f' ("{item["name"].strip()}")'
        errors += [f"{label}: {problem}" for problem in problems]
        recipes.append(recipe)

    if len(errors) > MAX_ERRORS:
        errors = errors[:MAX_ERRORS] + [f"...and {len(errors) - MAX_ERRORS} more problems."]
    return ([] if errors else recipes), errors


# Claude sometimes wraps JSON in ```json ... ``` even when asked not to
def _strip_code_fence(text):
    match = re.fullmatch(r"```[a-zA-Z]*\s*\n(.*?)\n?\s*```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def validate_recipe(item):
    """Check one recipe from the JSON and clean it up.

    Returns (recipe, problems). recipe is ready for db.create_recipe;
    problems is a list of messages like "missing 'servings'".
    """
    if not isinstance(item, dict):
        return None, ["should be an object like {\"name\": ..., \"servings\": ...}"]

    problems = []

    name = item.get("name")
    if "name" not in item:
        problems.append("missing 'name'")
    elif not isinstance(name, str) or not name.strip():
        problems.append("'name' should be some text")

    servings = item.get("servings")
    if isinstance(servings, str) and servings.strip().isdigit():
        servings = int(servings)   # "4" is fine too
    if "servings" not in item:
        problems.append("missing 'servings'")
    elif isinstance(servings, bool) or not isinstance(servings, int) or servings < 1:
        problems.append("'servings' should be a whole number, 1 or more")

    ingredients = []
    if "ingredients" not in item:
        problems.append("missing 'ingredients'")
    elif not isinstance(item["ingredients"], list):
        problems.append("'ingredients' should be a list [ ... ]")
    else:
        for number, ing in enumerate(item["ingredients"], start=1):
            ingredient, problem = _validate_ingredient(ing)
            if problem:
                problems.append(f"ingredient {number}: {problem}")
            elif ingredient:
                ingredients.append(ingredient)

    steps = item.get("steps")
    if "steps" not in item:
        problems.append("missing 'steps'")
    elif isinstance(steps, str):
        steps = steps.splitlines()   # one string is fine: one step per line
    elif not (isinstance(steps, list) and all(isinstance(s, str) for s in steps)):
        problems.append("'steps' should be a list of text, or one piece of text")

    tags = item.get("tags", [])   # tags are optional
    if isinstance(tags, str):
        tags = tags.split(",")
    if not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        problems.append("'tags' should be a list of text like [\"dinner\", \"quick\"]")

    if problems:
        return None, problems
    return {
        "name": name.strip(),
        "servings": servings,
        "ingredients": ingredients,
        "steps": "\n".join(s.strip() for s in steps if s.strip()),
        "tags": db.parse_tags(",".join(tags)),
    }, []


# One ingredient: an object {"amount", "unit", "name"}, or a plain line of
# text like "2 cups flour" (which goes through the line parser).
# Returns (ingredient, problem). A blank text line returns (None, None): skipped.
def _validate_ingredient(ing):
    if isinstance(ing, str):
        if not ing.strip():
            return None, None
        return parse_ingredient_line(ing), None
    if not isinstance(ing, dict):
        return None, "should be an object like {\"amount\": \"1\", \"unit\": \"cup\", \"name\": \"flour\"}"

    name = ing.get("name")
    if "name" not in ing:
        return None, "missing 'name'"
    if not isinstance(name, str) or not name.strip():
        return None, "'name' should be some text"

    fields = {"name": name.strip()}
    for key in ("amount", "unit"):
        value = ing.get(key)
        if value is None:
            value = ""
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            value = _number_text(value)   # 2 -> "2", 0.5 -> "1/2"
        elif not isinstance(value, str):
            return None, f"'{key}' should be text like \"1/2\""
        fields[key] = value.strip()
    fields["unit"] = normalize_unit(fields["unit"])   # "Tablespoons" -> "tbsp"
    return {"amount": fields["amount"], "unit": fields["unit"], "name": fields["name"]}, None


def _number_text(value):
    if not math.isfinite(value):
        return str(value)   # JSON "Infinity" or "NaN": kept as text, never scaled
    if isinstance(value, int) or value == int(value):
        return str(int(value))
    return _tidy_amount(repr(value))


def to_json_format(recipe):
    """A saved-style recipe dict back in the recipes.json format (steps as a list)."""
    return {
        "name": recipe["name"],
        "servings": recipe["servings"],
        "tags": recipe["tags"],
        "ingredients": recipe["ingredients"],
        "steps": recipe["steps"].splitlines(),
    }


def recipes_to_json(recipes):
    """Pretty JSON text for a list of recipes (what goes in the paste box)."""
    data = [to_json_format(r) for r in recipes]
    if len(data) == 1:
        data = data[0]
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Duplicates and saving
# ---------------------------------------------------------------------------

def name_key(name):
    # "Pancakes " and "pancakes" count as the same name
    return " ".join(name.split()).casefold()


def find_duplicates(recipes, existing_names):
    """Positions (0, 1, ...) of recipes whose name is already taken.

    A name counts as taken if a saved recipe has it, or an earlier recipe in
    the same import does. Capitals and extra spaces are ignored.
    """
    taken = {name_key(n) for n in existing_names}
    duplicates = set()
    for position, recipe in enumerate(recipes):
        key = name_key(recipe["name"])
        if key in taken:
            duplicates.add(position)
        taken.add(key)
    return duplicates


def save_recipes(recipes, save_anyway=(), db_path=db.DEFAULT_DB_PATH):
    """Save the recipes, skipping duplicates unless their position is in save_anyway.

    Returns (saved_ids, skipped_names).
    """
    existing = [r["name"] for r in db.list_recipes(db_path=db_path)]
    duplicates = find_duplicates(recipes, existing)
    saved_ids, skipped = [], []
    for position, recipe in enumerate(recipes):
        if position in duplicates and position not in save_anyway:
            skipped.append(recipe["name"])
        else:
            saved_ids.append(db.create_recipe(**recipe, db_path=db_path))
    return saved_ids, skipped


# ---------------------------------------------------------------------------
# Import from a web link
# ---------------------------------------------------------------------------

def check_url(url):
    """Return the trimmed link, or raise ImportFailed if it isn't an http/https link."""
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ImportFailed("That doesn't look like a web link. It should start with http:// or https://.")
    return url


def fetch_html(url, timeout=URL_TIMEOUT):
    """Download a web page's HTML. Raises ImportFailed with a friendly message."""
    url = check_url(url)
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # A redirect could lead somewhere else, so check where we ended up
            check_url(response.geturl())
            raw = response.read(MAX_PAGE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except ImportFailed:
        raise
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ImportFailed("That site blocked the request (it doesn't allow apps to read its pages).")
        if e.code == 404:
            raise ImportFailed("That page wasn't found (error 404). Check the link.")
        raise SiteUnreachable(f"The site answered with an error ({e.code}). Try again later.")
    except (urllib.error.URLError, TimeoutError, OSError):
        # URLError: no internet, or the site name doesn't exist. TimeoutError: too slow.
        raise SiteUnreachable("Couldn't reach that site. Check your internet connection and the link.")
    except (ValueError, http.client.HTTPException):
        # A link Python can't use, or a site that sent back garbled data
        raise ImportFailed("Couldn't read that link. Check that it's copied correctly.")
    if len(raw) > MAX_PAGE_BYTES:
        raise ImportFailed("That page is too big to be a recipe page.")
    try:
        codecs.lookup(charset)
    except LookupError:
        charset = "utf-8"   # the site named a text encoding Python doesn't know
    return raw.decode(charset, errors="replace")


def recipe_from_url(url):
    """Download a recipe page and turn it into one of our recipe dicts.

    Returns (recipe, notes): notes are things worth checking in the preview,
    like "servings not found, using 4". Raises ImportFailed on any problem.
    """
    url = check_url(url)
    html = fetch_html(url)
    try:
        # supported_only=False: for sites the library doesn't know, still try
        # the standard recipe data (schema.org) that most recipe blogs include
        scraper = scrape_html(html, org_url=url, supported_only=False)
    except RecipeScrapersExceptions:
        raise ImportFailed("Couldn't find a recipe on that page. This site may not be supported.")
    except Exception:
        # Pages can be broken in surprising ways; never crash the app over one
        raise ImportFailed("Couldn't read a recipe from that page.")
    return recipe_from_scraper(scraper)


def recipe_from_scraper(scraper):
    """Turn a recipe-scrapers result into our recipe dict. Returns (recipe, notes)."""
    notes = []

    name = (_ask(scraper, "title") or "").strip()
    lines = _ask(scraper, "ingredients") or []
    ingredients = [parse_ingredient_line(line) for line in lines if str(line).strip()]
    if not name or not ingredients:
        raise ImportFailed("Couldn't find a recipe on that page. This site may not be supported.")

    servings = _servings_from_yields(_ask(scraper, "yields"))
    if servings is None:
        servings = DEFAULT_SERVINGS
        notes.append(f"The page didn't say how many servings, so it's set to {DEFAULT_SERVINGS}.")

    steps = _ask(scraper, "instructions_list")
    if not steps:
        steps = (_ask(scraper, "instructions") or "").splitlines()
    if not steps:
        notes.append("No steps were found on the page.")

    unparsed = sum(1 for ing in ingredients if not ing["amount"])
    if unparsed:
        notes.append(f"{unparsed} ingredient line(s) had no amount we could read; they're kept whole in the name.")

    recipe = {
        "name": name,
        "servings": servings,
        "ingredients": ingredients,
        "steps": "\n".join(str(s).strip() for s in steps if str(s).strip()),
        "tags": [],
    }
    return recipe, notes


# Ask the scraper for one field. Sites often leave fields out, and the
# library raises an error for that, so treat any error as "not there".
# A site's own scraper can also break when the site changes its layout, so
# if it gives nothing, try the standard recipe data (schema.org) on the page.
def _ask(scraper, field):
    for source in (scraper, getattr(scraper, "schema", None)):
        try:
            value = getattr(source, field)()
        except Exception:
            continue
        if value:
            return value
    return None


# "4 servings" -> 4, "Makes 12 cookies" -> 12, "4-6" -> 4, "" -> None
def _servings_from_yields(text):
    match = re.search(r"\d+", str(text or ""))
    if not match:
        return None
    servings = int(match.group())
    return servings if 1 <= servings <= 1000 else None
