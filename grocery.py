"""Grocery list: combine the ingredients of several recipes into one list.

Plain functions with no Flask or database code, like scaling.py. Amounts are
added up as exact Fractions and only rounded once at the very end.
"""

import re
from fractions import Fraction

import units
from scaling import format_amount, parse_amount


# Make text comparable: "  Butter " and "butter" both become "butter".
def normalize(text):
    return " ".join(text.split()).lower()


# Combine the ingredients of the picked recipes into one shopping list.
#
# picks: list of (recipe, servings) pairs. recipe is a dict like
#   db.get_recipe returns, and servings is how many people you're cooking for.
# system: "us" or "metric", which units to show the list in.
# Returns a list of {"amount", "unit", "name"} dicts sorted by name.
#
# Ingredients merge when their names match (ignoring capitals and extra
# spaces) and their units can be added up:
#   - Units we can convert merge by kind: "2 tbsp" + "1 cup" of butter is
#     one volume line, "8 oz" + "1 lb" of chicken is one weight line.
#     A volume and a weight of the same thing stay separate (we can't turn
#     cups of flour into grams without knowing how heavy flour is).
#   - Other units ("clove", "" for "3 eggs") only merge when they're the same.
def merge_ingredients(picks, system="us"):
    items = {}  # key -> what we've collected for that ingredient

    for recipe, servings in picks:
        factor = Fraction(servings, recipe["servings"])  # e.g. 8 of 4 -> x2

        for ing in recipe["ingredients"]:
            name = normalize(ing["name"])
            amount = parse_amount(ing["amount"])
            text = ing["amount"].strip()

            base = units.to_base(amount * factor, ing["unit"]) if amount is not None else None
            if base is not None:
                base_amount, kind = base
                key = (name, "kind", kind)   # e.g. ("butter", "kind", "volume")
            else:
                key = (name, "unit", normalize(ing["unit"]))

            if key not in items:
                # The first spelling we see is the one we show
                items[key] = {
                    "name": ing["name"].strip(),
                    "unit": ing["unit"].strip(),
                    "kind": base[1] if base else None,  # set: total is in base units
                    "total": None,     # Fraction, or None if no numbers yet
                    "other": [],       # amounts we can't add up, like "2-3"
                }
            item = items[key]

            if base is not None:
                item["total"] = (item["total"] or 0) + base_amount
            elif amount is not None:
                item["total"] = (item["total"] or 0) + amount * factor
            elif text and text not in item["other"]:
                item["other"].append(text)
            # A blank amount ("salt and pepper") adds nothing: it just makes
            # sure the item appears once on the list.

    grocery_list = []
    for item in items.values():
        amount, unit = _display_amount(item, system)
        grocery_list.append({"amount": amount, "unit": unit, "name": item["name"]})
    return sorted(grocery_list, key=lambda g: normalize(g["name"]))


# Build the amount text and unit for one grocery line, e.g. ("1 1/2", "cup"),
# ("2-3", "") or ("4 + 2-3", "") when some recipes gave a number and others
# gave text. Converted amounts are shown in the friendliest unit.
def _display_amount(item, system):
    if item["kind"] is not None:
        return units.from_base(item["total"], item["kind"], system, round_up=True)

    parts = []
    if item["total"] is not None:
        parts.append(format_amount(item["total"], round_up=True))
    parts.extend(item["other"])
    return " + ".join(parts), item["unit"]


# --- Aisles ---

# The order aisles appear on the grocery page (and in the copied text).
AISLES = ["Produce", "Dairy & Eggs", "Meat & Seafood", "Pantry", "Spices", "Frozen", "Other"]

# Words that put an ingredient in an aisle. Edit freely: add a word to the
# list of the aisle it belongs in. Write them in lower case and singular
# ("onion" also matches "onions"). Anything that matches nothing goes in Other.
#
# How a name is matched (see aisle_for below):
#   - Longer phrases win over single words, so "peanut butter" (Pantry)
#     beats "butter" (Dairy) and "chicken broth" beats "chicken".
#   - If two keywords are the same length, the one later in the name wins,
#     because the last word is usually the main thing: "egg noodles" are
#     noodles, "cream cheese" is cheese.
#   - The word "frozen" always means the Frozen aisle ("frozen peas").
AISLE_KEYWORDS = {
    "Produce": [
        "apple", "avocado", "banana", "basil", "bell pepper", "berry", "berries",
        "blueberry", "blueberries", "broccoli", "cabbage", "carrot", "celery",
        "cilantro", "cucumber", "fresh thyme", "fresh rosemary", "fresh herb", "garlic",
        "ginger", "grape", "green bean", "green onion", "kale", "leek", "lemon",
        "lettuce", "lime", "mint", "mushroom", "onion", "orange", "parsley",
        "potato", "potatoes", "scallion", "shallot", "spinach", "squash",
        "strawberry", "strawberries", "sweet potato", "tomato", "tomatoes", "zucchini",
    ],
    "Dairy & Eggs": [
        "butter", "buttermilk", "cheddar", "cheese", "cottage cheese", "cream",
        "cream cheese", "egg", "feta", "half and half", "heavy cream", "milk",
        "mozzarella", "parmesan", "ricotta", "sour cream", "yogurt",
    ],
    "Meat & Seafood": [
        "bacon", "beef", "chicken", "chorizo", "cod", "fish", "ground beef",
        "ground turkey", "ham", "lamb", "pork", "prosciutto", "salmon",
        "sausage", "shrimp", "steak", "tilapia", "tuna", "turkey",
    ],
    "Pantry": [
        "almond", "almond milk", "baking powder", "baking soda", "bean", "bread",
        "breadcrumb", "broth", "chickpea", "coconut milk", "cornstarch",
        "flour", "honey", "jam", "ketchup", "lentil", "maple syrup", "mayonnaise",
        "mustard", "noodle", "nut", "oat", "oil", "olive oil", "pasta",
        "peanut butter", "pecan", "rice", "soy sauce", "stock", "sugar",
        "syrup", "tomato paste", "tomato sauce", "canned tomato", "tortilla",
        "vanilla extract", "vinegar", "walnut",
    ],
    "Spices": [
        "black pepper", "chili powder", "cinnamon", "cumin", "dried thyme",
        "garlic powder", "nutmeg", "onion powder", "oregano", "paprika",
        "pepper", "red pepper flake", "rosemary", "salt", "seasoning", "thyme",
        "turmeric",
    ],
    "Frozen": [
        "frozen", "ice cream",
    ],
}


# Split a name into lower-case words, dropping numbers and punctuation:
# "Non-fat or 2% Greek yogurt" -> ["non", "fat", "or", "greek", "yogurt"]
def _words(text):
    return re.findall(r"[a-z]+", text.lower())


# True if word is keyword, or keyword with a plural ending ("onions", "peaches").
def _word_matches(word, keyword):
    return word in (keyword, keyword + "s", keyword + "es")


# Which aisle an ingredient name belongs in, e.g. "diced ham" -> "Meat & Seafood".
def aisle_for(name):
    words = _words(name)
    if "frozen" in words:
        return "Frozen"

    best = None  # (number of words in keyword, position in name, aisle)
    for aisle, keywords in AISLE_KEYWORDS.items():
        for keyword in keywords:
            parts = keyword.split()
            # Try the keyword at every position in the name
            for start in range(len(words) - len(parts) + 1):
                window = words[start:start + len(parts)]
                if all(_word_matches(w, k) for w, k in zip(window, parts)):
                    match = (len(parts), start, aisle)
                    if best is None or match[:2] > best[:2]:
                        best = match
    return best[2] if best else "Other"


# Put grocery list items under aisle headings, in the AISLES order.
# Returns a list of (aisle, items) pairs, leaving out empty aisles.
# Each item also gets a "key": a short id that stays the same when you switch
# US/metric, used by the page to remember which boxes you ticked.
def group_by_aisle(items):
    groups = {aisle: [] for aisle in AISLES}
    seen = {}  # name -> how many times we've seen it (butter by cup AND by weight)
    for item in items:
        name = normalize(item["name"])
        seen[name] = seen.get(name, 0) + 1
        key = name if seen[name] == 1 else f"{name}#{seen[name]}"
        groups[aisle_for(item["name"])].append({**item, "key": key})
    return [(aisle, groups[aisle]) for aisle in AISLES if groups[aisle]]


# One grocery item as a line of text: "1 1/2 cup butter", or just "salt".
def item_line(item):
    return " ".join(part for part in (item["amount"], item["unit"], item["name"]) if part)


# The list as plain text to paste into a notes app or a message:
#
#   Produce
#   - 2 large onion, sliced
#
#   Dairy & Eggs
#   - 6 eggs
#
# checked: keys of items already ticked off; they're left out, and so is an
# aisle with nothing left in it. (The copy button on the page builds the same
# text in JavaScript, because the ticks only live in the browser.)
def grocery_text(groups, checked=()):
    sections = []
    for aisle, items in groups:
        lines = [f"- {item_line(item)}" for item in items if item["key"] not in checked]
        if lines:
            sections.append("\n".join([aisle] + lines))
    return "\n\n".join(sections)
