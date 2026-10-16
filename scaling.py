"""Recipe scaling: turn ingredient amounts like "1 1/2" into numbers, scale
them, and turn them back into cooking-friendly text.

These are plain functions with no Flask or database code, so they are easy
to test on their own. All the math uses fractions.Fraction, which stores
numbers as exact fractions (1/3 stays exactly 1/3) instead of floats
(0.333...), so there are no rounding errors along the way.
"""

import re
from fractions import Fraction

# The fractions a home cook actually measures with. Scaled amounts are rounded
# to the nearest one of these. 0 and 1 are included so 0.95 can round up to a
# whole number and 0.05 can round down.
COOKING_FRACTIONS = [
    Fraction(0),
    Fraction(1, 8),
    Fraction(1, 4),
    Fraction(1, 3),
    Fraction(1, 2),
    Fraction(2, 3),
    Fraction(3, 4),
    Fraction(1),
]

# The amount formats we understand. Anything else (like "a pinch" or "2-3")
# is not a number we can scale, so it is left alone.
WHOLE_OR_DECIMAL = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")   # "2", "0.5", ".5"
FRACTION = re.compile(r"^\d+/\d+$")                       # "1/3"
MIXED_NUMBER = re.compile(r"^(\d+)\s+(\d+/\d+)$")         # "1 1/2"


# Turn amount text into an exact Fraction, e.g. "1 1/2" -> Fraction(3, 2).
# Returns None when the text is blank or isn't a number we understand.
def parse_amount(text):
    text = (text or "").strip()

    mixed = MIXED_NUMBER.match(text)
    if mixed:
        whole, fraction_part = mixed.groups()
        return Fraction(whole) + _parse_fraction(fraction_part)

    if FRACTION.match(text):
        return _parse_fraction(text)

    if WHOLE_OR_DECIMAL.match(text):
        # Fraction("0.5") is exactly 1/2, with no float in between
        return Fraction(text)

    return None


# Helper for "3/4" style text. Returns None for "1/0" instead of crashing.
def _parse_fraction(text):
    numerator, denominator = text.split("/")
    if int(denominator) == 0:
        return None
    return Fraction(int(numerator), int(denominator))


# Round to the nearest whole number plus a common cooking fraction,
# e.g. 1.3 -> 1 1/3 and 0.9 -> 1. With round_up=True it goes to the next
# cooking fraction up instead (5/6 -> 1), which a shopping list wants so
# you never buy too little. fractions lets a caller allow fewer choices
# (units.py only allows halves for tablespoons).
def round_to_cooking_fraction(value, round_up=False, fractions=COOKING_FRACTIONS):
    whole = value.numerator // value.denominator   # the whole-number part (floor)
    leftover = value - whole                        # what's left, between 0 and 1
    if round_up:
        # The smallest cooking fraction that's at least the leftover.
        # The list always ends with 1, so there's always one.
        chosen = min(f for f in fractions if f >= leftover)
    else:
        # The cooking fraction closest to the leftover. On a tie, min() keeps
        # the first (smaller) one.
        chosen = min(fractions, key=lambda f: abs(f - leftover))
    return whole + chosen


# Turn a Fraction into text a cook can read: "2", "1/3" or "1 1/2".
# Never returns decimals like 0.3333. Pass round_up=True for shopping lists.
def format_amount(value, round_up=False, fractions=COOKING_FRACTIONS):
    rounded = round_to_cooking_fraction(value, round_up, fractions)
    # A real (but tiny) amount shouldn't round down to "0": show 1/8 instead
    if value > 0 and rounded == 0:
        rounded = Fraction(1, 8)

    whole, remainder = divmod(rounded.numerator, rounded.denominator)
    fraction_part = f"{remainder}/{rounded.denominator}"

    if remainder == 0:
        return str(whole)            # "3"
    if whole == 0:
        return fraction_part         # "1/3"
    return f"{whole} {fraction_part}"  # "1 1/2"


# Scale one amount from a recipe's serving count to a new one and return
# display text, e.g. ("1/3", 2, 6) -> "1". Blank or non-numeric amounts like
# "a pinch" come back unchanged.
def scale_amount(text, from_servings, to_servings):
    amount = parse_amount(text)
    if amount is None or from_servings < 1:
        return text
    return format_amount(amount * Fraction(to_servings, from_servings))
