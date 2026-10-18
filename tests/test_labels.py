"""Tests for labels.py: guessing a recipe's protein and meal type."""

import pytest

import labels


def ing(amount, unit, name):
    return {"amount": amount, "unit": unit, "name": name}


def proteins(name, ingredients, tags=()):
    return labels.guess_labels(name, ingredients, tags)[0]


def meal_type(name, ingredients=(), tags=()):
    return labels.guess_labels(name, list(ingredients), tags)[1]


# --- Which ingredient names count as a protein ---

@pytest.mark.parametrize("name, expected", [
    ("chicken thighs or breasts", {"chicken"}),
    ("boneless skinless chicken breasts, cubed", {"chicken"}),
    ("lean ground beef", {"beef"}),
    ("beef short ribs", {"beef"}),
    ("flank steak", {"beef"}),
    ("thick-cut bacon", {"pork"}),
    ("diced ham", {"pork"}),
    ("Italian sausage", {"pork"}),
    ("salmon fillets", {"fish"}),
    ("anchovies", {"fish"}),
    ("large shrimp, peeled and deveined", {"fish"}),
    ("ground lamb", {"eggs-other"}),
    ("ground turkey", {"eggs-other"}),
    ("eggs", {"egg"}),
    ("egg yolks", {"egg"}),
    ("chicken and mushrooms", {"chicken"}),
    # Another animal named: not pork
    ("turkey bacon", {"eggs-other"}),
    ("chicken sausage", {"chicken"}),
    # Both named: both count
    ("ground pork and beef", {"pork", "beef"}),
])
def test_protein_ingredients(name, expected):
    assert labels.proteins_in(name) == expected


@pytest.mark.parametrize("name", [
    "chicken broth",
    "low-sodium chicken stock",
    "chicken or vegetable broth",
    "beef bouillon cubes",
    "chicken-flavored ramen",
    "Better Than Bouillon chicken base",
    "fish sauce",
    "oyster sauce",
    "oyster mushrooms",
    "clam juice",
    "egg noodles",
    "egg roll wrappers",
    "bacon grease",
    "vegan sausage",
    "plant-based beef crumbles",
    "eggplant",
    "hamburger buns",
    "graham crackers",
    "chickpeas",
])
def test_not_a_protein(name):
    assert labels.proteins_in(name) == set()


def test_text_after_a_comma_is_ignored():
    # "stock" is about the shells, not the shrimp
    assert labels.proteins_in("shrimp, peeled (save shells for stock)") == {"fish"}


@pytest.mark.parametrize("name", [
    # The meat comes after a comma (imported recipes write it like this)
    "boneless, skinless chicken breasts",
    "boneless, skinless chicken breasts (, each breast sliced in half lengthwise)",
    "skin-on, bone-in chicken thighs",
])
def test_meat_after_a_comma_still_counts(name):
    assert labels.proteins_in(name) == {"chicken"}


def test_meat_only_in_a_bracket_note_does_not_count():
    assert labels.proteins_in("baby spinach (or chicken stock, if you like)") == set()


def test_marry_me_chicken_is_chicken():
    ingredients = [
        ing("1 1/2", "lb", "boneless, skinless chicken breasts (, each breast sliced in half)"),
        ing("1", "cup", "chicken stock"),
        ing("1", "cup", "heavy cream"),
        ing("3", "cup", "baby spinach"),
    ]
    assert proteins("Marry Me Chicken", ingredients) == ["chicken"]


# --- Size estimates ---

@pytest.mark.parametrize("amount, unit, name, grams", [
    ("1", "lb", "chicken", 454),
    ("2", "tbsp", "bacon bits", 30),
    ("6", "", "eggs", 300),
    ("4", "slices", "bacon", 80),
    ("1", "pinch", "bacon bits", 1),
    ("", "", "bacon bits", 5),          # garnish with no amount: tiny
    ("", "", "chicken", 50),            # no amount: smallish guess
    ("2-3", "", "chicken breasts", 300),  # a range: the first number
])
def test_estimate_grams(amount, unit, name, grams):
    assert labels.estimate_grams(ing(amount, unit, name)) == pytest.approx(grams, abs=1)


# --- Whole recipes: proteins ---

def test_broth_does_not_make_a_soup_chicken():
    assert proteins("Lentil Soup", [
        ing("1", "cup", "red lentils"),
        ing("4", "cup", "chicken broth"),
        ing("1", "", "onion"),
    ]) == ["vegetarian"]


def test_bacon_bits_do_not_outweigh_the_main_protein():
    assert proteins("Loaded Chicken Bake", [
        ing("2", "lb", "chicken breasts"),
        ing("2", "tbsp", "bacon bits"),
        ing("1", "cup", "shredded cheddar"),
    ]) == ["chicken"]


def test_bacon_bits_alone_still_mean_pork():
    # Not vegetarian: it does have meat in it
    assert proteins("Wedge Salad", [
        ing("1", "", "head iceberg lettuce"),
        ing("2", "tbsp", "bacon bits"),
    ]) == ["pork"]


def test_two_big_proteins_both_count():
    assert proteins("Paella", [
        ing("1", "lb", "chicken thighs"),
        ing("1", "lb", "shrimp"),
        ing("2", "cup", "rice"),
    ]) == ["chicken", "fish"]


def test_fish_sauce_and_anchovy_paste_do_not_make_fish():
    assert proteins("Beef Pho", [
        ing("1", "lb", "beef sirloin, thinly sliced"),
        ing("2", "tbsp", "fish sauce"),
        ing("8", "cup", "beef broth"),
    ]) == ["beef"]


def test_meat_free_recipe_is_vegetarian():
    assert proteins("Bean Chili", [
        ing("2", "can", "black beans"),
        ing("1", "can", "diced tomatoes"),
    ]) == ["vegetarian"]


def test_eggs_as_the_main_thing():
    assert proteins("Veggie Frittata", [
        ing("8", "", "eggs"),
        ing("1", "cup", "spinach"),
    ]) == ["eggs-other"]


def test_a_couple_of_eggs_in_pancakes_is_vegetarian():
    assert proteins("Pancakes", [
        ing("2", "cup", "flour"),
        ing("2", "", "eggs"),
        ing("1 1/2", "cup", "milk"),
    ]) == ["vegetarian"]


def test_eggs_in_a_dessert_are_vegetarian():
    assert proteins("Pound Cake", [
        ing("4", "", "eggs"),
        ing("2", "cup", "flour"),
    ], tags=["dessert"]) == ["vegetarian"]


def test_eggs_with_a_little_meat_count_as_both():
    # The seed quiche: 6 eggs and 1 cup of ham
    assert proteins("Ham Quiche", [
        ing("6", "", "eggs"),
        ing("1", "cup", "diced ham"),
    ]) == ["pork", "eggs-other"]


def test_eggs_used_as_a_binder_do_not_count():
    assert proteins("Meatloaf", [
        ing("2", "lb", "ground beef"),
        ing("2", "", "eggs"),
    ]) == ["beef"]


def test_other_meats_go_under_eggs_other():
    assert proteins("Lamb Kofta", [ing("1", "lb", "ground lamb")]) == ["eggs-other"]


def test_no_ingredients_is_vegetarian():
    assert proteins("Mystery", []) == ["vegetarian"]


# --- Whole recipes: meal type ---

@pytest.mark.parametrize("name, tags, expected", [
    ("Chicken Stroganoff", ["dinner"], "main"),
    ("Anything", ["Side Dish"], "side"),
    ("Anything", ["brunch"], "breakfast"),
    ("Anything", ["dessert"], "dessert"),
    ("Anything", ["snack"], "other"),
    ("Blueberry Pancakes", [], "breakfast"),
    ("Chocolate Chip Cookies", [], "dessert"),
    ("Apple Pie", [], "dessert"),
    ("Garlic Mashed Potatoes", [], "side"),
    ("Greek Salad", [], "side"),
    ("Basil Pesto", [], "other"),
    ("Tomato Soup", [], "main"),
    ("Vegetable Pot Pie", [], "main"),   # "pot pie" is a main, not a dessert
    ("Stir-fried Tofu", [], "main"),     # the default
])
def test_meal_type_from_tags_and_name(name, tags, expected):
    assert meal_type(name, tags=tags) == expected


def test_a_salad_with_meat_is_a_main():
    assert meal_type("Chicken Caesar Salad", [ing("1", "lb", "chicken breasts")]) == "main"


def test_tags_beat_the_name():
    assert meal_type("Chicken Caesar Salad", [ing("1", "lb", "chicken")], tags=["side"]) == "side"


def test_hand_picked_meal_type_is_used_for_the_egg_rule():
    # Called "dessert" by hand: its eggs don't make it "eggs/other"
    found, kind = labels.guess_labels("Custard", [ing("6", "", "egg yolks")], meal_type="dessert")
    assert kind == "dessert"
    assert found == ["vegetarian"]


# --- Small helpers ---

def test_clean_proteins_keeps_known_keys_in_chip_order():
    assert labels.clean_proteins(["pork", "nonsense", "chicken", "pork"]) == ["chicken", "pork"]


def test_clean_meal_type():
    assert labels.clean_meal_type("side") == "side"
    assert labels.clean_meal_type("brunch") == ""


def test_count_proteins_counts_each_label():
    recipes = [{"proteins": ["chicken"]}, {"proteins": ["chicken", "fish"]}, {"proteins": ["vegetarian"]}]
    counts = labels.count_proteins(recipes)
    assert counts == {"chicken": 2, "beef": 0, "pork": 0, "fish": 1, "vegetarian": 1, "eggs-other": 0}
