# Recipe import prompt

Paste this into a Claude chat, then paste or type a recipe right after it.
Copy Claude's answer (the JSON) into the **Import** page of the app, under
"Paste JSON". The same prompt is on that page with a "Copy prompt" button.

The app's code keeps its own copy in `importer.py` (`CLAUDE_PROMPT`); a test
checks that this file and the app say the same thing.

```text
Turn the recipe below into JSON for my recipe app.

Rules:
- Output ONLY valid JSON. No explanation before or after, no markdown, no code fences.
- Use exactly this format. For several recipes, put them in a list: [ {...}, {...} ]

{
  "name": "Garlic Butter Pasta",
  "servings": 4,
  "tags": ["dinner", "quick"],
  "ingredients": [
    {"amount": "1", "unit": "lb", "name": "spaghetti"},
    {"amount": "1 1/2", "unit": "tbsp", "name": "butter"},
    {"amount": "4", "unit": "", "name": "garlic cloves, minced"},
    {"amount": "", "unit": "", "name": "salt to taste"}
  ],
  "steps": [
    "Boil the spaghetti until al dente.",
    "Melt the butter and cook the garlic for 1 minute.",
    "Toss the pasta with the garlic butter and season."
  ]
}

- "servings" is a whole number.
- "amount" is text: a whole number or a fraction like "1/2" or "1 1/2". No decimals like 0.5 and no fraction characters like ½.
- "unit" is one of: tsp, tbsp, cup, oz, lb, g, kg, ml, l. Use "" for counts (like 3 eggs) and put other words such as "clove" or "can" in the name.
- When there is no exact amount (like "salt to taste" or "oil for frying"), leave "amount" and "unit" as "".
- Put preparation notes in the name after a comma, like "onion, diced".
- "steps" has one string per step, in order.
- "tags" has a few short lowercase tags, like dinner, breakfast, vegetarian, quick.

Recipe:
```
