# Recipe App

Personal recipe and meal prep web app. Owner is a beginner-intermediate
Python/Java coder learning Claude Code and GitHub, so explain what you build
in plain language and keep code simple and readable.

## Stack
- Python, Flask, SQLite, plain HTML/CSS (mobile-friendly, no heavy frameworks)
- Small bits of vanilla JS are fine when needed (e.g. copy button, check-offs)

## V1 (DONE, merged)
1. Add/edit/delete recipes (name, servings, ingredients with amount + unit, steps, tags)
2. Scale a recipe to any serving count (handle fractions like 1/3 cup)
3. Pick several recipes for the week and generate one merged grocery list

## V2 roadmap (build in this order, one branch + PR each)
1. (DONE) Unit conversion: normalize units, simplify when scaling (12 tsp -> 1/4 cup),
   US/metric toggle, and merge compatible units in the grocery list
2. (DONE) Grocery list polish: check-off boxes, group by aisle, copy as text
3. (DONE) Home page search (name + ingredient) and clickable tag filter
4. (DONE) Recipe import: paste-JSON page (for output from a Claude chat) + import from a URL
5. (DONE) Phone access: free cloud deploy with a simple password gate and recipe export/backup
   (hosted on PythonAnywhere free tier; owner's setup steps are in DEPLOY.md)

## V3 roadmap (build in this order, one branch + PR each)
The app is local-first for now: it runs on the owner's computer and stays free.
No hosting or deploy work unless asked (DEPLOY.md stays for later).
A. (DONE) Browse by protein + one-tap "Add to this week" (plan saved in the database;
   label guessing rules are in labels.py)
B. Fresh finds: suggestions that refresh themselves when the app opens, with one-click import
C. Side dish pairing

## Rules
- This week's plan is saved in the database (one current plan); old ?recipe=... plan URLs must not crash
- Add tests for any new logic (units, merging, parsing, filtering, import)
- Keep recipes.json as seed data; never overwrite the user's recipes.db
- Never commit secrets (passwords, keys, .env). Use environment variables.

## Git workflow (Claude Code does this autonomously)
- Start each feature from an up-to-date, clean main on branch feature/<name>
- Small commits with clear messages
- Run the full pytest suite before pushing; fix failures first
- Push, open a PR with gh (plain-language summary + decisions made), and if
  tests pass squash-merge it, delete the branch, and return to updated main
- If gh is missing/unauthenticated, commit locally and tell the owner what is needed
- Never force-push; never touch anything outside this repo
- Don't pause for plan approval; decide sensibly and record decisions in the PR

## Run
python app.py  (then open http://localhost:5000)
Tests: python -m pytest  (activate venv first; Windows/PowerShell)
