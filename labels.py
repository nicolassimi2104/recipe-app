"""Guess a recipe's protein and meal type from its name, ingredients and tags.

Plain rules with no AI and no internet, like aisle_for in grocery.py, and
no Flask or database code, so it's easy to test. The steps:

1. Find the protein ingredients ("chicken thighs", "diced ham", "eggs"),
   skipping things that only taste of one ("chicken broth", "fish sauce",
   "egg noodles", "vegan sausage").
2. Estimate how big each one is in grams, roughly: "1 1/2 lb" is about
   680 g, "2 tbsp" about 30 g, "6" eggs about 300 g, a pinch about 1 g.
3. The biggest meat or fish is the main protein. Others count too if they're
   at least a third of its size (chicken AND shrimp in a paella), so a
   sprinkle of bacon bits doesn't make a chicken dinner "pork".
4. Eggs count when they're the main thing: 3 or more (or an egg dish like
   an omelet), not a dessert, and at least as big as any meat.
5. No meat, fish or main eggs: "vegetarian".
"""

import re
from collections import Counter

import units
from scaling import parse_amount

# Labels saved in the database -> names shown on the page, in chip order
PROTEINS = {
    "chicken": "Chicken",
    "beef": "Beef",
    "pork": "Pork",
    "fish": "Fish & seafood",
    "vegetarian": "Vegetarian",
    "eggs-other": "Eggs/other",
}

MEAL_TYPES = ["main", "side", "breakfast", "dessert", "other"]

# Words that mean a meat or fish. Plurals match too ("thighs" is fine, since
# only the keyword itself needs to appear: "chicken thighs" has "chicken").
MEAT_WORDS = {
    "chicken": ["chicken", "cornish hen"],
    "beef": ["beef", "steak", "brisket", "sirloin", "ribeye", "chuck roast", "veal",
             "short rib", "oxtail"],
    "pork": ["pork", "bacon", "ham", "prosciutto", "pancetta", "chorizo", "sausage",
             "salami", "pepperoni", "guanciale", "hot dog", "bratwurst", "kielbasa"],
    "fish": ["fish", "seafood", "salmon", "tuna", "cod", "tilapia", "halibut", "trout",
             "haddock", "pollock", "catfish", "swordfish", "mahi", "snapper", "bass",
             "sardine", "anchovy", "mackerel", "shrimp", "prawn", "scallop", "crab",
             "lobster", "clam", "mussel", "oyster", "squid", "calamari", "octopus",
             "crawfish"],
    # Meats that aren't one of the four above go under "Eggs/other"
    "eggs-other": ["turkey", "duck", "lamb", "goat", "venison", "bison", "rabbit", "mutton"],
}

# Sausage, bacon and friends are pork unless the name says another animal:
# "turkey bacon" is other, "chicken sausage" is chicken.
PORK_UNLESS_SAID = {"bacon", "ham", "sausage", "hot dog", "pepperoni", "salami"}

EGG_WORDS = ["egg", "yolk"]

# If one of these comes right after the meat word, it's a flavouring, not the
# meat: "chicken broth", "beef bouillon cubes", "fish sauce", "egg noodles",
# "bacon grease", "oyster mushrooms", "egg roll wrappers"
NOT_THE_MEAT_AFTER = {
    "broth", "stock", "bouillon", "base", "sauce", "paste", "fat", "grease",
    "drippings", "gravy", "juice", "seasoning", "flavor", "flavored", "flavour",
    "flavoured", "powder", "noodles", "noodle", "mushroom", "mushrooms", "bone",
    "bones", "wrappers", "wrapper", "roll", "rolls",
}
# If one of these is anywhere in the name, it's a meat-free stand-in
MEAT_FREE_WORDS = {"vegan", "vegetarian", "meatless", "plant"}

EGG_DISH_WORDS = ["egg", "eggs", "omelet", "omelette", "frittata", "shakshuka", "scramble",
                  "scrambled", "quiche"]

# Rough sizes in grams for units that aren't volume or weight
OTHER_UNIT_GRAMS = {
    "pinch": 1, "dash": 1, "sprinkle": 2, "handful": 30,
    "slice": 20, "strip": 20, "rasher": 20, "piece": 100, "fillet": 150,
    "can": 150, "tin": 150, "package": 400, "pkg": 400, "pack": 400,
}
# One "6 eggs" is about 300 g; a plain count of meat is about a breast or fillet
COUNT_GRAMS = {"egg": 50, "yolk": 20, "shrimp": 20, "prawn": 20, "scallop": 25}
DEFAULT_COUNT_GRAMS = 150
NO_AMOUNT_GRAMS = 50   # "chicken, to taste": we don't know, guess smallish
GARNISH_GRAMS = 5      # "bacon bits for topping" with no amount
GARNISH_WORDS = {"bits", "garnish", "topping", "optional", "crumbles"}

# Meal type words. Tags are checked first, then the recipe name.
MEAL_TAG_WORDS = [
    ("dessert", {"dessert", "desserts", "sweet", "sweets"}),
    ("breakfast", {"breakfast", "brunch"}),
    ("side", {"side", "sides"}),
    ("other", {"snack", "snacks", "sauce", "sauces", "drink", "drinks", "dip", "dressing",
               "condiment", "condiments", "appetizer", "appetizers"}),
]
BREAKFAST_NAMES = ["breakfast", "pancake", "waffle", "oatmeal", "oats", "granola", "parfait",
                   "smoothie", "french toast", "omelet", "omelette", "frittata", "scrambled",
                   "shakshuka", "muffin"]
# A name with one of these is a main dish even if it also says "pie" or "salad"
MAIN_NAMES = ["soup", "stew", "chili", "curry", "pasta", "lasagna", "casserole", "pizza",
              "burrito", "taco", "sandwich", "pot pie", "risotto", "stir fry"]
DESSERT_NAMES = ["dessert", "cake", "cupcake", "cookie", "brownie", "blondie", "pie", "tart",
                 "pudding", "ice cream", "cheesecake", "fudge", "cobbler", "crumble", "crisp",
                 "mousse", "sorbet", "tiramisu", "sundae", "trifle", "custard"]
SIDE_NAMES = ["side", "salad", "slaw", "coleslaw", "mashed", "pilaf", "fries", "garlic bread",
              "cornbread", "roasted vegetables", "green beans", "brussels sprouts",
              "asparagus", "broccoli"]
OTHER_NAMES = ["sauce", "dressing", "dip", "salsa", "pesto", "vinaigrette", "hummus",
               "guacamole", "marinade", "seasoning", "lemonade"]


# ---------------------------------------------------------------------------
# Word matching (same idea as grocery.aisle_for)
# ---------------------------------------------------------------------------

# Split text into lower-case words: "Chicken Thighs, bone-in" -> ["chicken", "thighs", "bone", "in"]
def _words(text):
    return re.findall(r"[a-z]+", text.lower())


# True if word is keyword or a plural of it ("eggs", "anchovies", "peaches").
def _word_matches(word, keyword):
    if word in (keyword, keyword + "s", keyword + "es"):
        return True
    return keyword.endswith("y") and word == keyword[:-1] + "ies"


# Where keyword (one or more words) appears in words: a list of
# (start, end) positions, e.g. "short rib" in "beef short ribs" -> [(1, 3)].
def _find(words, keyword):
    parts = keyword.split()
    spots = []
    for start in range(len(words) - len(parts) + 1):
        window = words[start:start + len(parts)]
        if all(_word_matches(w, k) for w, k in zip(window, parts)):
            spots.append((start, start + len(parts)))
    return spots


def _has_any(words, keywords):
    return any(_find(words, keyword) for keyword in keywords)


# ---------------------------------------------------------------------------
# Step 1: which proteins is this ingredient?
# ---------------------------------------------------------------------------

# Labels this one ingredient name counts towards, e.g. "chicken thighs" ->
# {"chicken"}, "turkey bacon" -> {"eggs-other"}, "chicken broth" -> set().
# Eggs come back as "egg" (not a label yet; step 4 decides).
def proteins_in(ingredient_name):
    # Only look at the part before a comma or bracket: in "shrimp, peeled
    # (save the shells for stock)" the word "stock" isn't about the shrimp
    head = re.split(r"[,(]", ingredient_name, maxsplit=1)[0]
    words = _words(head)
    if MEAT_FREE_WORDS & set(words):
        return set()

    def is_flavouring(end):
        # The word right after the meat: "chicken BROTH". For "chicken OR
        # vegetable broth", look at the last word instead.
        after = words[end:end + 1]
        if after == ["or"]:
            after = words[-1:]
        return bool(NOT_THE_MEAT_AFTER & set(after))

    def is_real(keyword):
        return any(not is_flavouring(end) for _, end in _find(words, keyword))

    found = {}  # label -> the keywords that matched
    for label, keywords in MEAT_WORDS.items():
        for keyword in keywords:
            if is_real(keyword):
                found.setdefault(label, set()).add(keyword)

    # "chicken sausage": drop the pork guess when another animal is named
    pork = found.get("pork", set())
    if pork and pork <= PORK_UNLESS_SAID and len(found) > 1:
        del found["pork"]

    labels = set(found)
    if not labels and any(is_real(keyword) for keyword in EGG_WORDS):
        labels.add("egg")
    return labels


# ---------------------------------------------------------------------------
# Step 2: roughly how big is this ingredient?
# ---------------------------------------------------------------------------

# The first number in an amount we can't fully read, e.g. "2-3" -> 2.
def _first_number(text):
    match = re.search(r"\d+(\.\d+)?", text or "")
    return float(match.group()) if match else None


# A size for an unusual unit like "slices" or "pinch", or None if unknown.
def _other_unit_grams(unit):
    unit = unit.lower().strip(" .")
    for form in (unit, unit[:-1], unit[:-2]):   # "slices" -> "slice", "pinches" -> "pinch"
        if form in OTHER_UNIT_GRAMS:
            return OTHER_UNIT_GRAMS[form]
    return None


# Rough size in grams. Volumes count 1 ml as 1 g (close enough to compare).
def estimate_grams(ingredient):
    words = _words(ingredient["name"])
    amount = parse_amount(ingredient.get("amount", ""))
    if amount is None:
        amount = _first_number(ingredient.get("amount", ""))
    if amount is None:
        return GARNISH_GRAMS if GARNISH_WORDS & set(words) else NO_AMOUNT_GRAMS
    amount = float(amount)

    unit = ingredient.get("unit", "").strip()
    base = units.to_base(amount, unit) if unit else None
    if base is not None:
        return float(base[0])   # ml or g
    if unit:
        per_unit = _other_unit_grams(unit)
        return amount * (per_unit if per_unit is not None else DEFAULT_COUNT_GRAMS)

    # Just a count, like "6 eggs" or "4 chicken breasts"
    for keyword, grams in COUNT_GRAMS.items():
        if _has_any(words, [keyword]):
            return amount * grams
    return amount * DEFAULT_COUNT_GRAMS


# ---------------------------------------------------------------------------
# Steps 3-5: put it together
# ---------------------------------------------------------------------------

# Total grams of each meat/fish label and of eggs, for a list of ingredients.
def protein_sizes(ingredients):
    sizes = Counter()
    for ing in ingredients:
        for label in proteins_in(ing["name"]):
            sizes[label] += estimate_grams(ing)
    return sizes


# Guess both labels at once. Returns (proteins, meal_type), where proteins
# is a list of PROTEINS keys in chip order. Pass meal_type if it's already
# known (set by hand), since eggs in a dessert don't count.
def guess_labels(name, ingredients, tags=(), meal_type=None):
    sizes = protein_sizes(ingredients)
    eggs = sizes.pop("egg", 0)
    biggest = max(sizes.values(), default=0)
    # Step 3: the main meat or fish, plus any at least a third its size
    proteins = {label for label, grams in sizes.items() if grams >= biggest / 3}

    if meal_type is None:
        meal_type = guess_meal_type(name, tags, has_meat=bool(proteins))

    # Step 4: eggs, when they're the main thing
    egg_dish = _has_any(_words(name), EGG_DISH_WORDS)
    if eggs and meal_type != "dessert" and (eggs >= 150 or egg_dish) and eggs >= biggest:
        proteins.add("eggs-other")

    # Step 5: nothing found
    if not proteins:
        proteins.add("vegetarian")
    return [key for key in PROTEINS if key in proteins], meal_type


# "main" unless the tags or name say otherwise. A recipe with meat or fish
# isn't guessed as a dessert, side or sauce from its name ("Chicken Caesar
# Salad" is a main), but tags always win.
def guess_meal_type(name, tags=(), has_meat=False):
    tag_words = set(_words(" ".join(tags)))
    for meal_type, words in MEAL_TAG_WORDS:
        if tag_words & words:
            return meal_type

    name_words = _words(name)
    if _has_any(name_words, BREAKFAST_NAMES):
        return "breakfast"
    if has_meat or _has_any(name_words, MAIN_NAMES):
        return "main"
    for meal_type, keywords in (("dessert", DESSERT_NAMES), ("side", SIDE_NAMES),
                                ("other", OTHER_NAMES)):
        if _has_any(name_words, keywords):
            return meal_type
    return "main"


# ---------------------------------------------------------------------------
# Reading the form and the home page chips
# ---------------------------------------------------------------------------

# Keep only real protein keys, in chip order, no duplicates.
def clean_proteins(values):
    return [key for key in PROTEINS if key in values]


# Keep a meal type only if it's one we know, else "" (meaning "guess it").
def clean_meal_type(value):
    return value if value in MEAL_TYPES else ""


# How many recipes have each protein: {"chicken": 2, "beef": 0, ...}.
# A recipe with two proteins counts under both.
def count_proteins(recipes):
    counts = {key: 0 for key in PROTEINS}
    for recipe in recipes:
        for key in recipe["proteins"]:
            if key in counts:
                counts[key] += 1
    return counts
