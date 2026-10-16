"""Tests for grocery.py: merging the ingredients of several recipes."""

from fractions import Fraction

import pytest

import grocery
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


def test_compatible_units_merge_into_one_line():
    a = recipe(4, ("2", "tbsp", "butter"))
    b = recipe(4, ("1", "cup", "Butter"))

    # 2 tbsp + 1 cup = 1 1/8 cup
    assert merge_ingredients([(a, 4), (b, 4)]) == [
        {"amount": "1 1/8", "unit": "cup", "name": "butter"}
    ]


def test_merged_amount_is_simplified():
    a = recipe(4, ("4", "tbsp", "chicken broth"))
    b = recipe(4, ("4", "tablespoons", "chicken broth"))

    # 8 tbsp is 1/2 cup
    assert merge_ingredients([(a, 4), (b, 4)])[0] == {
        "amount": "1/2", "unit": "cup", "name": "chicken broth"
    }


def test_weights_merge_across_units():
    a = recipe(4, ("8", "oz", "chicken"))
    b = recipe(4, ("1", "lb", "chicken"))
    c = recipe(4, ("250", "g", "chicken"))

    # 8 oz + 16 oz + 250 g (8.8 oz) = about 32.8 oz, rounded up to 2 1/4 lb
    assert merge_ingredients([(a, 4), (b, 4), (c, 4)])[0]["amount"] == "2 1/4"


def test_volume_and_weight_stay_separate():
    # We can't turn cups into ounces without knowing how heavy the food is
    a = recipe(4, ("1", "cup", "flour"))
    b = recipe(4, ("4", "oz", "flour"))

    result = merge_ingredients([(a, 4), (b, 4)])

    assert {"amount": "1", "unit": "cup", "name": "flour"} in result
    assert {"amount": "4", "unit": "oz", "name": "flour"} in result


def test_unknown_units_stay_separate():
    a = recipe(4, ("2", "clove", "garlic"))
    b = recipe(4, ("1", "tsp", "garlic"))

    assert len(merge_ingredients([(a, 4), (b, 4)])) == 2


def test_text_amount_with_a_unit_gets_its_own_line():
    a = recipe(4, ("1", "tbsp", "olive oil"))
    b = recipe(4, ("2-3", "tbsp", "olive oil"))

    result = merge_ingredients([(a, 4), (b, 4)])

    assert {"amount": "1", "unit": "tbsp", "name": "olive oil"} in result
    assert {"amount": "2-3", "unit": "tbsp", "name": "olive oil"} in result


def test_metric_grocery_list():
    a = recipe(4, ("1", "cup", "milk"), ("1", "lb", "beef"), ("3", "", "eggs"))
    b = recipe(4, ("2", "tbsp", "milk"))

    result = merge_ingredients([(a, 4), (b, 4)], system="metric")

    # Rounded up: 1 cup + 2 tbsp is about 266 ml -> 270
    assert {"amount": "270", "unit": "ml", "name": "milk"} in result
    assert {"amount": "460", "unit": "g", "name": "beef"} in result
    assert {"amount": "3", "unit": "", "name": "eggs"} in result


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


# --- Aisles ---

@pytest.mark.parametrize(
    "name, aisle",
    [
        ("large onion, sliced", "Produce"),
        ("Mushrooms, sliced", "Produce"),          # capitals and plurals
        ("garlic cloves, minced", "Produce"),
        ("diced ham", "Meat & Seafood"),
        ("chicken thighs or breasts", "Meat & Seafood"),
        ("heavy cream", "Dairy & Eggs"),
        ("eggs", "Dairy & Eggs"),
        ("non-fat or 2% Greek yogurt", "Dairy & Eggs"),  # numbers and dashes ignored
        ("cream cheese, softened", "Dairy & Eggs"),
        # Tricky ones: a longer phrase beats a single word
        ("peanut butter", "Pantry"),               # not Dairy because of "butter"
        ("chicken broth", "Pantry"),               # not Meat because of "chicken"
        ("garlic powder", "Spices"),               # not Produce because of "garlic"
        ("coconut milk", "Pantry"),                # not Dairy because of "milk"
        # Same length: the later word is the main thing
        ("egg noodles", "Pantry"),
        ("honey or maple syrup", "Pantry"),
        ("salt and pepper", "Spices"),
        ("frozen peas", "Frozen"),                 # "frozen" always wins
        ("dragon fruit", "Other"),                 # nothing matches
        ("", "Other"),
    ],
)
def test_aisle_for(name, aisle):
    assert grocery.aisle_for(name) == aisle


def test_keywords_match_whole_words_only():
    # "ham" is inside "graham" but graham crackers aren't meat
    assert grocery.aisle_for("graham crackers") == "Other"


def test_every_keyword_aisle_is_a_real_aisle():
    assert set(grocery.AISLE_KEYWORDS) <= set(grocery.AISLES)


def item(amount, unit, name):
    return {"amount": amount, "unit": unit, "name": name}


def test_group_by_aisle_keeps_aisle_order_and_skips_empty_aisles():
    items = [item("1", "tsp", "salt"), item("2", "", "eggs"), item("1", "", "onion")]

    groups = grocery.group_by_aisle(items)

    assert [aisle for aisle, _ in groups] == ["Produce", "Dairy & Eggs", "Spices"]
    assert groups[0][1] == [{"amount": "1", "unit": "", "name": "onion", "key": "onion"}]


def test_group_by_aisle_gives_repeated_names_different_keys():
    # Butter by volume and by weight can't merge, so it's on the list twice
    items = [item("1", "cup", "Butter"), item("8", "oz", "butter")]

    [(aisle, butter)] = grocery.group_by_aisle(items)

    assert [b["key"] for b in butter] == ["butter", "butter#2"]


# --- Copy as text ---

def test_grocery_text_groups_by_aisle():
    groups = grocery.group_by_aisle(
        [item("2", "", "eggs"), item("1 1/2", "cup", "butter"), item("", "", "salt"), item("1", "", "onion")]
    )

    assert grocery.grocery_text(groups) == (
        "Produce\n"
        "- 1 onion\n"
        "\n"
        "Dairy & Eggs\n"
        "- 2 eggs\n"
        "- 1 1/2 cup butter\n"
        "\n"
        "Spices\n"
        "- salt"                      # no amount: just the name
    )


def test_grocery_text_leaves_out_checked_items_and_empty_aisles():
    groups = grocery.group_by_aisle([item("2", "", "eggs"), item("1", "", "onion"), item("1", "", "lemon")])

    text = grocery.grocery_text(groups, checked={"eggs", "lemon"})

    assert text == "Produce\n- 1 onion"


def test_grocery_text_everything_checked_is_empty():
    groups = grocery.group_by_aisle([item("2", "", "eggs")])

    assert grocery.grocery_text(groups, checked={"eggs"}) == ""
