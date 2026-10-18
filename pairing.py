"""Pick side dishes that go with a main dish.

Plain rules with no AI and no internet, and no Flask or database code, like
labels.py, so it's easy to test. The steps:

1. Look at what the main already has (labels.plate_parts):
   - no vegetables: a vegetable or salad comes first, whatever the starch.
     (So a starch-heavy main, like chicken and potatoes, gets balanced by a veg.)
   - vegetables but no starch: a starch comes first.
   - both: any side type is fine.
2. Score every side: 2 points for a wanted side type, 1 for the same
   cuisine as the main (a main with cuisine "other" gets no cuisine point).
   So a wanted type always beats a cuisine match, and a side with neither
   still shows up when there's nothing better (the fallback).
3. Sort by score. Sides with the same score are put in a random order
   that's always the same for this main, so the page doesn't jump around
   on every reload.
4. Show 3. "Shuffle" shows the next 3 down the list, going back to the top
   after the last one, so each shuffle gives a different set.
"""

import random

import labels

HOW_MANY = 3

TYPE_POINTS = 2
CUISINE_POINTS = 1

# Why these sides come first, shown above the suggestions
REASONS = {
    "no-veg": "This dish has no vegetables, so veggie sides and salads come first.",
    "no-starch": "This dish has vegetables but no starch, so rice, potatoes and the like come first.",
    "both": "This dish already has a starch and vegetables, so any side works.",
}


def wanted_side_types(main):
    """(side types to put first, reason key) for a main dish dict."""
    has_starch, has_veg = labels.plate_parts(main["ingredients"])
    if not has_veg:
        return {"vegetable", "salad"}, "no-veg"
    if not has_starch:
        return {"starch"}, "no-starch"
    return set(), "both"


def score(side, wanted_types, cuisine):
    """How well one side fits: higher is better (0 to 3)."""
    points = 0
    if side.get("side_type") in wanted_types:
        points += TYPE_POINTS
    if cuisine and cuisine != "other" and side.get("cuisine") == cuisine:
        points += CUISINE_POINTS
    return points


def rank_sides(main, sides):
    """Every side (except the main itself), best fit first."""
    wanted_types, _ = wanted_side_types(main)
    candidates = [side for side in sides if side["id"] != main["id"]]
    # Random order first, then a stable sort by score keeps that order
    # among sides with the same score. Seeding with the main's id makes
    # the "random" order the same every time for this main.
    random.Random(main["id"]).shuffle(candidates)
    candidates.sort(key=lambda side: score(side, wanted_types, main.get("cuisine")),
                    reverse=True)
    return candidates


def pick_sides(main, sides, shuffle=0, how_many=HOW_MANY):
    """The sides to show for this main: set number `shuffle` (0 is the best).

    With 3 or fewer sides, there's only one set, so shuffle shows the same.
    """
    ranked = rank_sides(main, sides)
    if len(ranked) <= how_many:
        return ranked
    start = (shuffle * how_many) % len(ranked)
    return [ranked[(start + i) % len(ranked)] for i in range(how_many)]
