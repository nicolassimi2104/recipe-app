"""Tests for grocery.py: merging the ingredients of several recipes."""

from fractions import Fraction

import pytest

from grocery import merge_ingredients
from scaling import format_amount


# Build a small recipe dict, shaped like the ones db.get_recipe returns
def recipe(servings, *ingredients):
    return {
        "servings": servings,
        "ingredients": [{"amount": a, "unit": u, "name": n} for a, u, n in ingredients],
    }


# --- Rounding up for shopping ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (Fraction(5, 6), "1"),        # nearest would be 3/4: too little to buy
        (Fraction(1, 10), "1/8"),
        (Fraction(11, 5), "2 1/4"),   # 2.2 -> 2 1/4 (nearest would be 2 1/4 too)
        (Fraction(21, 10), "2 1/8"),  # 2.1 -> 2 1/8 (nearest would be 2 1/8)
        (Fraction(13, 10), "1 1/3"),  # 1.3 -> 1 1/3
        (Fraction(7, 20), "1/2"),     # 0.35 is just over 1/3, so up to 1/2
        (Fraction(1, 3), "1/3"),      # exact cooking fractions stay as they are
        (Fraction(4), "4"),
    ],
)
def test_round_up_never_rounds_down(value, expected):
    assert format_amount(value, round_up=True) == expected


# --- Merging ---

def test_same_ingredient_and_unit_adds_up():
    a = recipe(4, ("1/2", "cup", "heavy cream"))
    b = recipe(4, ("1/3", "cup", "heavy cream"))

    # 1/2 + 1/3 = 5/6, rounded UP to 1 so you buy enough
    assert merge_ingredients([(a, 4), (b, 4)]) == [
        {"amount": "1", "unit": "cup", "name": "heavy cream"}
    ]


def test_mixed_numbers_add_up_exactly():
    a = recipe(4, ("1 1/2", "lb", "chicken"))
    b = recipe(4, ("2 1/2", "lb", "chicken"))

    assert merge_ingredients([(a, 4), (b, 4)])[0]["amount"] == "4"


def test_capitals_and_spaces_are_ignored_when_matching():
    a = recipe(2, ("2", "tbsp", "Butter"))
    b = recipe(2, ("1", "TBSP ", "  butter "))

    assert merge_ingredients([(a, 2), (b, 2)]) == [
        {"amount": "3", "unit": "tbsp", "name": "Butter"}  # first spelling wins
    ]


def test_different_units_stay_separate():
    a = recipe(4, ("1", "cup", "chicken broth"))
    b = recipe(4, ("4", "tbsp", "chicken broth"))

    result = merge_ingredients([(a, 4), (b, 4)])

    assert {"amount": "1", "unit": "cup", "name": "chicken broth"} in result
    assert {"amount": "4", "unit": "tbsp", "name": "chicken broth"} in result
    assert len(result) == 2


def test_different_names_stay_separate():
    # Exact name matching only, for now
    a = recipe(4, ("10", "oz", "mushrooms, sliced"))
    b = recipe(4, ("8", "oz", "mushrooms"))

    assert len(merge_ingredients([(a, 4), (b, 4)])) == 2


def test_each_recipe_is_scaled_before_adding():
    a = recipe(4, ("1/2", "cup", "rice"))   # cooking for 8: doubles to 1
    b = recipe(2, ("1/2", "cup", "rice"))   # cooking for 1: halves to 1/4

    assert merge_ingredients([(a, 8), (b, 1)])[0]["amount"] == "1 1/4"


def test_blank_amount_appears_once_with_no_amount():
    a = recipe(4, ("", "", "salt and pepper"))
    b = recipe(4, ("", "", "Salt and pepper"))

    assert merge_ingredients([(a, 4), (b, 4)]) == [
        {"amount": "", "unit": "", "name": "salt and pepper"}
    ]


def test_blank_amount_does_not_hide_a_real_amount():
    a = recipe(4, ("", "", "eggs"))
    b = recipe(4, ("6", "", "eggs"))

    assert merge_ingredients([(a, 4), (b, 4)])[0]["amount"] == "6"


def test_text_amounts_are_kept_next_to_numbers():
    a = recipe(4, ("4", "", "garlic cloves"))
    b = recipe(4, ("2-3", "", "garlic cloves"))

    assert merge_ingredients([(a, 4), (b, 4)])[0]["amount"] == "4 + 2-3"


def test_list_is_sorted_by_name():
    a = recipe(4, ("1", "", "Zucchini"), ("1", "", "apple"), ("1", "", "Milk"))

    names = [g["name"] for g in merge_ingredients([(a, 4)])]
    assert names == ["apple", "Milk", "Zucchini"]


def test_nothing_picked_gives_empty_list():
    assert merge_ingredients([]) == []
