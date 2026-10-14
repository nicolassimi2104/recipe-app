# Recipe App

Personal recipe and meal prep web app. Owner is a beginner-intermediate
Python/Java coder learning Claude Code and GitHub, so explain what you build
in plain language and keep code simple and readable.

## Stack
- Python, Flask, SQLite, plain HTML/CSS (mobile-friendly, no heavy frameworks)

## V1 features
1. Add/edit/delete recipes (name, servings, ingredients with amount + unit, steps, tags)
2. Scale a recipe to any serving count (handle fractions like 1/3 cup)
3. Pick several recipes for the week and generate one merged grocery list

## Rules
- Build one feature at a time; propose a plan before writing code
- Add tests for scaling and grocery-list merging logic
- Small commits with clear messages; work on a branch per feature
- Seed data lives in recipes.json and imports on first run

## Run
python app.py  (then open http://localhost:5000)
