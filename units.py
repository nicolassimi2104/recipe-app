"""Unit conversion: understand unit spellings, convert between units, and
pick the friendliest unit to show an amount in.

Plain functions with no Flask or database code, like scaling.py.

How it works: every unit we know is either a VOLUME (tsp, cup, ml...) or a
WEIGHT (oz, lb, g...). To convert, an amount is first turned into a "base"
amount (millilitres for volume, grams for weight), and then turned back into
whichever unit reads best. All the math uses exact Fractions, and rounding
only happens at the very end, when the amount is turned into text.

Units we don't know ("pinch", "clove", or no unit at all for "3 eggs") are
never converted: they're left exactly as typed.
"""

import math
from fractions import Fraction

from scaling import (
    COOKING_FRACTIONS,
    format_amount,
    parse_amount,
    round_to_cooking_fraction,
)

# Exact sizes from the official US definitions
FL_OZ_ML = Fraction("29.5735295625")   # 1 US fluid ounce in millilitres
TSP_ML = FL_OZ_ML / 6                  # 1 teaspoon (about 4.93 ml)
TBSP_ML = TSP_ML * 3                   # 1 tablespoon (about 14.8 ml)
CUP_ML = FL_OZ_ML * 8                  # 1 cup (about 237 ml)
OZ_G = Fraction("28.349523125")        # 1 ounce (weight) in grams
LB_G = OZ_G * 16                       # 1 pound (about 454 g)

# Every unit we can convert: its kind, and how big it is in base units
# (millilitres for volume, grams for weight).
UNITS = {
    "tsp": ("volume", TSP_ML),
    "tbsp": ("volume", TBSP_ML),
    "fl oz": ("volume", FL_OZ_ML),
    "cup": ("volume", CUP_ML),
    "ml": ("volume", Fraction(1)),
    "l": ("volume", Fraction(1000)),
    "oz": ("weight", OZ_G),            # "oz" always means weight; use "fl oz" for liquids
    "lb": ("weight", LB_G),
    "g": ("weight", Fraction(1)),
    "kg": ("weight", Fraction(1000)),
}

US_UNITS = {"tsp", "tbsp", "fl oz", "cup", "oz", "lb"}

# Other ways people write each unit. Matching ignores capitals, extra spaces
# and full stops, so "Tbsp.", "TBSP" and "tbsp" are all the same.
ALIASES = {
    "tsp": ["teaspoon", "teaspoons", "tsps", "tsp"],
    "tbsp": ["tablespoon", "tablespoons", "tbsps", "tbs", "tbl", "tbsp"],
    "fl oz": ["fluid ounce", "fluid ounces", "floz", "fl oz", "fl ozs"],
    "cup": ["cups", "c", "cup"],
    "ml": ["milliliter", "milliliters", "millilitre", "millilitres", "mls", "ml"],
    "l": ["liter", "liters", "litre", "litres", "ltr", "l"],
    "oz": ["ounce", "ounces", "ozs", "oz"],
    "lb": ["pound", "pounds", "lbs", "lb"],
    "g": ["gram", "grams", "gr", "g"],
    "kg": ["kilogram", "kilograms", "kilo", "kilos", "kgs", "kg"],
}
# Flip ALIASES around into one lookup table: "tablespoons" -> "tbsp"
_ALIAS_TO_UNIT = {alias: unit for unit, aliases in ALIASES.items() for alias in aliases}

# Tablespoons are only shown in halves: "1 1/2 tbsp" is easy, "1 1/3 tbsp" isn't
HALVES = [Fraction(0), Fraction(1, 2), Fraction(1)]
# Pounds skip eighths: "1 1/4 lb" yes, "1 1/8 lb" no (that reads better as 18 oz)
NO_EIGHTHS = [f for f in COOKING_FRACTIONS if f != Fraction(1, 8)]

# Which US units to try for each kind, biggest first. Each one is used only
# for amounts in its range (in base units, max not included).
# For example tablespoons are for 1 tbsp up to (not including) 1/2 cup.
# The ranges overlap on purpose: 4 tsp could be tsp or tbsp, and since
# "1 1/3 tbsp" isn't clean in halves, it stays "4 tsp".
US_CHOICES = {
    "volume": [
        # (unit, min, max, fractions allowed)
        ("cup", CUP_ML / 4, None, COOKING_FRACTIONS),
        ("tbsp", TBSP_ML, CUP_ML / 2, HALVES),
        ("tsp", Fraction(0), TBSP_ML * 3, COOKING_FRACTIONS),
    ],
    "weight": [
        ("lb", LB_G, None, NO_EIGHTHS),
        ("oz", Fraction(0), LB_G * 2, COOKING_FRACTIONS),
    ],
}

# A unit is "clean enough" when rounding to a cooking fraction changes the
# amount by at most 5%. Otherwise we try the next smaller unit.
TOLERANCE = Fraction(5, 100)


# Turn any spelling of a unit into its standard name: "Tablespoons" -> "tbsp".
# Units we don't know ("pinch", "clove", "") come back as typed, just trimmed.
def normalize_unit(text):
    text = (text or "").strip()
    key = " ".join(text.lower().replace(".", "").split())
    return _ALIAS_TO_UNIT.get(key, text)


# Is this unit one we can convert? (tsp, cup, g... yes; pinch, clove... no)
def is_convertible(unit):
    return normalize_unit(unit) in UNITS


# "us" or "metric" for a unit we know, None for one we don't.
def system_of(unit):
    unit = normalize_unit(unit)
    if unit not in UNITS:
        return None
    return "us" if unit in US_UNITS else "metric"


# Turn an amount in some unit into base units: (Fraction, kind).
# e.g. (2, "tbsp") -> (about 29.6, "volume"). Returns None for units we
# can't convert.
def to_base(amount, unit):
    unit = normalize_unit(unit)
    if unit not in UNITS:
        return None
    kind, size = UNITS[unit]
    return amount * size, kind


# Turn a base amount back into display text in the chosen system ("us" or
# "metric"). Returns (amount_text, unit), e.g. (about 59 ml, "volume", "us")
# -> ("1/4", "cup"). round_up=True is for shopping lists.
def from_base(base, kind, system="us", round_up=False):
    if system == "metric":
        return _metric(base, kind, round_up)
    return _us(base, kind, round_up)


# Pick the friendliest US unit: the biggest one whose range fits the amount
# and that gives a clean number. If none is clean, use the biggest that fits.
# e.g. 3 tsp -> "1 tbsp", 12 tsp -> "1/4 cup", 4 tsp stays "4 tsp".
def _us(base, kind, round_up):
    fits = [
        choice for choice in US_CHOICES[kind]
        if base >= choice[1] and (choice[2] is None or base < choice[2])
    ]
    for unit, _, _, fractions in fits:
        value = base / UNITS[unit][1]
        if _is_clean(value, fractions, round_up):
            return format_amount(value, round_up, fractions), unit

    unit, _, _, fractions = fits[0]
    return format_amount(base / UNITS[unit][1], round_up, fractions), unit


# True when the amount, rounded to one of the allowed fractions, is within
# TOLERANCE of the real amount.
def _is_clean(value, fractions, round_up):
    rounded = round_to_cooking_fraction(value, round_up, fractions)
    return abs(rounded - value) <= value * TOLERANCE


# Metric amounts are shown as round numbers instead of fractions:
#   under 10       -> nearest 1     (4.9 ml -> 5 ml)
#   10 to 100      -> nearest 5     (59 ml -> 60 ml)
#   100 to 1000    -> nearest 10    (237 ml -> 240 ml)
#   1000 and over  -> litres or kilos to 1 decimal (1361 g -> 1.4 kg)
def _metric(base, kind, round_up):
    small, large = ("ml", "l") if kind == "volume" else ("g", "kg")

    if base < 10:
        step = 1
    elif base < 100:
        step = 5
    else:
        step = 10
    rounded = _round_to_step(base, step, round_up)
    if base > 0 and rounded == 0:
        rounded = Fraction(1)   # a real (tiny) amount shouldn't show as "0 ml"

    if rounded >= 1000:
        return _decimal_text(_round_to_step(base / 1000, Fraction(1, 10), round_up)), large
    return _decimal_text(rounded), small


# Round to a multiple of step, e.g. (59, 5) -> 60. Halves round up (like
# school maths) so results are predictable. round_up=True always goes up.
def _round_to_step(value, step, round_up):
    if round_up:
        return math.ceil(value / step) * Fraction(step)
    return math.floor(value / step + Fraction(1, 2)) * Fraction(step)


# Fraction -> "240" or "1.4" (no trailing ".0")
def _decimal_text(value):
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):g}"


# Work out what to show for one ingredient on a recipe page.
# Returns (amount_text, unit).
#
# factor is how much to scale by (2 = double the recipe). system is "us"
# or "metric". The rules, in order:
#   - Amounts that aren't numbers ("a pinch", "2-3", blank) are left as typed.
#   - Units we can't convert ("clove", "" for "3 eggs") are only scaled.
#   - If nothing changes (not scaled, already in the chosen system) the
#     amount is shown exactly as typed, so "6 tsp" you typed stays "6 tsp".
#   - Otherwise it's converted and shown in the friendliest unit.
def show_ingredient(amount_text, unit, factor=1, system="us"):
    amount = parse_amount(amount_text)
    if amount is None:
        return amount_text, unit

    base = to_base(amount * factor, unit)
    if base is None:
        if factor == 1:
            return amount_text, unit
        return format_amount(amount * factor), unit

    if factor == 1 and system_of(unit) == system:
        return amount_text, unit
    return from_base(*base, system=system)
