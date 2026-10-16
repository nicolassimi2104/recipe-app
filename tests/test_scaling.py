"""Tests for scaling.py: reading amounts, rounding them, and scaling them."""

from fractions import Fraction

import pytest

from scaling import format_amount, parse_amount, scale_amount


# --- parse_amount ---

@pytest.mark.parametrize(
    "text, expected",
    [
        ("2", Fraction(2)),                # whole number
        ("12", Fraction(12)),
        ("1/3", Fraction(1, 3)),           # fraction
        ("3/4", Fraction(3, 4)),
        ("1 1/2", Fraction(3, 2)),         # mixed number
        ("2  1/4", Fraction(9, 4)),        # extra space is fine
        ("0.5", Fraction(1, 2)),           # decimal, exactly 1/2
        ("1.25", Fraction(5, 4)),
        (" 2 ", Fraction(2)),              # spaces around it are ignored
    ],
)
def test_parse_amount_understands_numbers(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "pinch", "a pinch", "2-3", "1/0", "abc"])
def test_parse_amount_returns_none_for_non_numbers(text):
    assert parse_amount(text) is None


# --- format_amount ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (Fraction(3), "3"),
        (Fraction(1, 3), "1/3"),
        (Fraction(3, 2), "1 1/2"),
        (Fraction(2, 3), "2/3"),
        (Fraction(1, 8), "1/8"),
        (Fraction(3, 10), "1/3"),          # 0.3 is closest to 1/3
        (Fraction(9, 10), "1"),            # 0.9 rounds up to a whole number
        (Fraction(59, 20), "3"),           # 2.95 -> 3
        (Fraction(13, 10), "1 1/3"),       # 1.3 -> 1 1/3
        (Fraction(1, 100), "1/8"),         # tiny amounts never show as "0"
        (Fraction(0), "0"),
    ],
)
def test_format_amount_uses_cooking_fractions(value, expected):
    assert format_amount(value) == expected


def test_format_amount_never_shows_decimals():
    # Try lots of awkward values; none should come out with a decimal point
    for numerator in range(1, 200):
        assert "." not in format_amount(Fraction(numerator, 7))


# --- scale_amount ---

def test_one_third_cup_times_three_is_one_cup():
    assert scale_amount("1/3", 2, 6) == "1"


def test_one_half_halved_is_one_quarter():
    assert scale_amount("1/2", 4, 2) == "1/4"


def test_one_and_a_half_doubled_is_three():
    assert scale_amount("1 1/2", 4, 8) == "3"


def test_one_third_doubled_is_two_thirds():
    assert scale_amount("1/3", 4, 8) == "2/3"


def test_decimal_amount_scales_to_a_fraction():
    assert scale_amount("0.5", 2, 3) == "3/4"


def test_same_servings_gives_same_amount():
    assert scale_amount("3/4", 6, 6) == "3/4"


@pytest.mark.parametrize("text", ["", "a pinch", "2-3"])
def test_non_numeric_amounts_come_back_unchanged(text):
    assert scale_amount(text, 4, 8) == text
