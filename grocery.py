"""Grocery list: combine the ingredients of several recipes into one list.

Plain functions with no Flask or database code, like scaling.py. Amounts are
added up as exact Fractions and only rounded once at the very end.
"""

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
