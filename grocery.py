"""Grocery list: combine the ingredients of several recipes into one list.

Plain functions with no Flask or database code, like scaling.py. Amounts are
added up as exact Fractions and only rounded once at the very end.
"""

from fractions import Fraction

from scaling import format_amount, parse_amount


# Make text comparable: "  Butter " and "butter" both become "butter".
def normalize(text):
    return " ".join(text.split()).lower()


# Combine the ingredients of the picked recipes into one shopping list.
#
# picks: list of (recipe, servings) pairs. recipe is a dict like
#   db.get_recipe returns, and servings is how many people you're cooking for.
# Returns a list of {"amount", "unit", "name"} dicts sorted by name.
#
# Ingredients merge when their name AND unit match (ignoring capitals and
# extra spaces). Different units stay as separate lines: no unit conversion yet.
def merge_ingredients(picks):
    items = {}  # (name, unit) -> what we've collected for that ingredient

    for recipe, servings in picks:
        factor = Fraction(servings, recipe["servings"])  # e.g. 8 of 4 -> x2

        for ing in recipe["ingredients"]:
            key = (normalize(ing["name"]), normalize(ing["unit"]))
            if key not in items:
                # The first spelling we see is the one we show
                items[key] = {
                    "name": ing["name"].strip(),
                    "unit": ing["unit"].strip(),
                    "total": None,     # Fraction, or None if no numbers yet
                    "other": [],       # amounts we can't add up, like "2-3"
                }
            item = items[key]

            amount = parse_amount(ing["amount"])
            text = ing["amount"].strip()
            if amount is not None:
                item["total"] = (item["total"] or 0) + amount * factor
            elif text and text not in item["other"]:
                item["other"].append(text)
            # A blank amount ("salt and pepper") adds nothing: it just makes
            # sure the item appears once on the list.

    grocery_list = []
    for item in items.values():
        grocery_list.append(
            {"amount": _display_amount(item), "unit": item["unit"], "name": item["name"]}
        )
    return sorted(grocery_list, key=lambda g: normalize(g["name"]))


# Build the amount text for one grocery line, e.g. "1 1/2", "2-3" or
# "4 + 2-3" when some recipes gave a number and others gave text.
def _display_amount(item):
    parts = []
    if item["total"] is not None:
        parts.append(format_amount(item["total"], round_up=True))
    parts.extend(item["other"])
    return " + ".join(parts)
