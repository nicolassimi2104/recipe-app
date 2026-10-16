"""Tests for units.py: unit names, conversion, and picking friendly units."""

from fractions import Fraction

import pytest

from scaling import format_amount
from units import from_base, normalize_unit, show_ingredient, system_of, to_base


# Convert "amount unit" straight to display text in a system, e.g.
# show("12", "tsp") -> "1/4 cup". Shorter to read in the tests below.
def show(amount, unit, system="us", round_up=False):
    amount_text, new_unit = from_base(*to_base(Fraction(amount), unit), system, round_up)
    return f"{amount_text} {new_unit}"


# --- Unit names ---

@pytest.mark.parametrize(
    "text, expected",
    [
        ("tsp", "tsp"), ("teaspoons", "tsp"), ("Tsp.", "tsp"),
        ("tablespoon", "tbsp"), ("TBSP", "tbsp"), ("Tbs", "tbsp"),
        ("cups", "cup"), ("C", "cup"),
        ("fl oz", "fl oz"), ("fl. oz.", "fl oz"), ("fluid ounces", "fl oz"),
        ("ounces", "oz"), ("OZ", "oz"),
        ("lbs", "lb"), ("pound", "lb"),
        ("grams", "g"), ("kilo", "kg"),
        ("mL", "ml"), ("millilitres", "ml"),
        ("litre", "l"), ("L", "l"),
        ("  tbsp  ", "tbsp"),
    ],
)
def test_normalize_unit_understands_common_spellings(text, expected):
    assert normalize_unit(text) == expected


@pytest.mark.parametrize("text", ["pinch", "clove", "", "large", "Slices"])
def test_unknown_units_are_left_as_typed(text):
    assert normalize_unit(text) == text


def test_oz_means_weight_and_fl_oz_means_volume():
    assert to_base(Fraction(1), "oz")[1] == "weight"
    assert to_base(Fraction(1), "fl oz")[1] == "volume"


def test_counts_and_unknown_units_cant_be_converted():
    assert to_base(Fraction(3), "") is None        # "3 eggs"
    assert to_base(Fraction(1), "pinch") is None


def test_system_of():
    assert system_of("Tablespoons") == "us"
    assert system_of("grams") == "metric"
    assert system_of("clove") is None


# --- Exact conversions ---

def test_us_units_relate_exactly():
    tsp = to_base(Fraction(1), "tsp")[0]
    assert to_base(Fraction(1), "tbsp")[0] == 3 * tsp
    assert to_base(Fraction(1), "cup")[0] == 48 * tsp
    assert to_base(Fraction(1), "cup")[0] == 8 * to_base(Fraction(1), "fl oz")[0]
    assert to_base(Fraction(1), "lb")[0] == 16 * to_base(Fraction(1), "oz")[0]


# --- Picking the friendliest US unit ---

@pytest.mark.parametrize(
    "amount, unit, expected",
    [
        (3, "tsp", "1 tbsp"),
        (12, "tsp", "1/4 cup"),
        (6, "tsp", "2 tbsp"),                     # 1/8 cup is too small for cups
        (2, "tsp", "2 tsp"),
        (4, "tsp", "4 tsp"),                      # not "1 1/3 tbsp"
        (Fraction(1, 2), "tsp", "1/2 tsp"),
        (8, "tbsp", "1/2 cup"),
        (6, "tbsp", "6 tbsp"),                    # 3/8 cup isn't a cooking fraction
        (Fraction(5, 6), "cup", "3/4 cup"),       # big amounts always stay in cups
        (16, "fl oz", "2 cup"),
        (18, "oz", "18 oz"),                      # not "1 1/8 lb"
        (20, "oz", "1 1/4 lb"),
        (32, "oz", "2 lb"),
        (8, "oz", "8 oz"),
    ],
)
def test_us_amounts_use_the_friendliest_unit(amount, unit, expected):
    assert show(Fraction(amount), unit) == expected


def test_metric_amounts_turn_into_us_units():
    assert show(240, "ml") == "1 cup"
    assert show(200, "g") == "7 oz"
    assert show(1, "kg") == "2 1/4 lb"


def test_round_up_for_shopping():
    # 5/12 cup: 1/2 cup would be 20% too much, so tablespoons: 6 2/3 -> 7
    assert show(Fraction(5, 12), "cup", round_up=True) == "7 tbsp"


# --- Metric ---

@pytest.mark.parametrize(
    "amount, unit, expected",
    [
        (1, "tsp", "5 ml"),
        (1, "tbsp", "15 ml"),
        (Fraction(1, 4), "cup", "60 ml"),
        (1, "cup", "240 ml"),
        (4, "cup", "950 ml"),
        (5, "cup", "1.2 l"),
        (Fraction(1, 8), "tsp", "1 ml"),          # tiny, but never "0 ml"
        (1, "oz", "30 g"),
        (1, "lb", "450 g"),
        (3, "lb", "1.4 kg"),
        (500, "g", "500 g"),
        (1000, "g", "1 kg"),
    ],
)
def test_metric_rounds_sensibly(amount, unit, expected):
    assert show(Fraction(amount), unit, "metric") == expected


def test_metric_round_up_never_rounds_down():
    assert show(1, "lb", "metric", round_up=True) == "460 g"     # 453.6 -> 460
    assert show(3, "lb", "metric", round_up=True) == "1.4 kg"    # 1.361 -> 1.4


# --- show_ingredient: what a recipe page shows ---

def test_unscaled_us_amount_is_shown_as_typed():
    assert show_ingredient("6", "tsp") == ("6", "tsp")
    assert show_ingredient("1/2", "Tablespoons") == ("1/2", "Tablespoons")


def test_scaled_amount_is_simplified():
    assert show_ingredient("1", "tsp", factor=3) == ("1", "tbsp")
    assert show_ingredient("3", "tsp", factor=4) == ("1/4", "cup")


def test_metric_converts_even_when_not_scaled():
    assert show_ingredient("1/2", "cup", system="metric") == ("120", "ml")
    assert show_ingredient("1", "lb", factor=2, system="metric") == ("910", "g")


def test_metric_amount_shown_as_typed_in_metric():
    assert show_ingredient("250", "g", system="metric") == ("250", "g")


def test_counts_and_unknown_units_are_only_scaled():
    assert show_ingredient("2", "", factor=2, system="metric") == ("4", "")
    assert show_ingredient("1", "pinch", factor=2, system="metric") == ("2", "pinch")
    assert show_ingredient("4", "clove", system="metric") == ("4", "clove")


@pytest.mark.parametrize("text", ["", "a pinch", "2-3"])
def test_amounts_that_arent_numbers_are_left_alone(text):
    assert show_ingredient(text, "tbsp", factor=2, system="metric") == (text, "tbsp")


def test_fraction_formatting_is_reused():
    # Same "1 1/2" style text as scaling.py
    assert show_ingredient("3", "cup", factor=Fraction(1, 2)) == (format_amount(Fraction(3, 2)), "cup")
