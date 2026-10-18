"""Recipe app: the Flask web server.

Run with:  python app.py   (then open http://localhost:5000)

Settings come from environment variables, so nothing secret is in the code.
None of them are needed for local use:
    APP_PASSWORD  if set, every page asks for this password first (for the hosted copy)
    SECRET_KEY    signs the login cookie; required when APP_PASSWORD is set
    DB_PATH       where the SQLite file lives (default: recipes.db next to this file)
    PORT          port for "python app.py" (default: 5000)
    SESSION_COOKIE_SECURE=1  only send the login cookie over https (set this when hosted)
"""

import hmac
import json
import os
import secrets
from datetime import date, timedelta
from fractions import Fraction
from urllib.parse import urlencode

from flask import (Flask, Response, abort, redirect, render_template, request,
                   session, url_for)

import db
import grocery
import importer
import labels
import units

# Upper limit for the "scale to" box, so a silly number can't make a huge page
MAX_SERVINGS = 1000


# Read the ?servings=N value from the URL. Anything missing, not a whole
# number, below 1 or above MAX_SERVINGS falls back to the recipe's own servings.
def requested_servings(text, original):
    try:
        servings = int(text)
    except (TypeError, ValueError):
        return original
    if 1 <= servings <= MAX_SERVINGS:
        return servings
    return original


# Read the ?units= value from the URL: "metric", or "us" for anything else
# (including no value at all, so US is the default).
def requested_units(text):
    return "metric" if text == "metric" else "us"


# For links: url_for leaves out values that are None, so this adds
# ?units=metric only when metric is on (US is the default).
def metric_or_none(system):
    return "metric" if system == "metric" else None


# Links for the US / Metric switch: the current page's URL with only the
# units value changed, so servings and picked recipes are kept.
def units_links(endpoint, **view_values):
    links = {}
    for system in ("us", "metric"):
        args = request.args.copy()
        args.pop("units", None)
        if system == "metric":
            args["units"] = "metric"   # US is the default, so it needs no value
        query = urlencode(list(args.items(multi=True)))
        links[system] = url_for(endpoint, **view_values) + ("?" + query if query else "")
    return links


def read_recipe_form(form):
    """Pull the recipe fields out of a submitted form.

    Returns (recipe, errors). recipe is a dict ready for db.create_recipe /
    db.update_recipe; errors is a list of messages to show the user.
    """
    errors = []

    name = form.get("name", "").strip()
    if not name:
        errors.append("Please enter a recipe name.")

    servings_text = form.get("servings", "").strip()
    servings = int(servings_text) if servings_text.isdigit() else 0
    if servings < 1:
        errors.append("Servings must be a whole number, 1 or more.")

    # Each ingredient row has three boxes with the same names, so getlist()
    # gives us three lists that line up: amounts[0], units[0], names[0] is row 1.
    amounts = form.getlist("amount")
    units = form.getlist("unit")
    names = form.getlist("ingredient_name")
    ingredients = []
    for amount, unit, ing_name in zip(amounts, units, names):
        if ing_name.strip():  # rows with no name are treated as empty and skipped
            ingredients.append(
                {"amount": amount.strip(), "unit": unit.strip(), "name": ing_name.strip()}
            )

    # One step per line; drop blank lines
    lines = form.get("steps", "").splitlines()
    steps = "\n".join(line.strip() for line in lines if line.strip())

    recipe = {
        "name": name,
        "servings": servings_text if errors else servings,
        "ingredients": ingredients,
        "steps": steps,
        "tags": db.parse_tags(form.get("tags", "")),
        # Labels left blank are guessed when saving (see labels.py)
        "proteins": labels.clean_proteins(form.getlist("protein")),
        "meal_type": labels.clean_meal_type(form.get("meal_type", "")),
    }
    return recipe, errors


# Only follow ?next=... if it's a page on this site ("/plan"), never another
# website ("https://evil.example" or "//evil.example"), so the login page
# can't be used to send someone elsewhere.
def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("index")


def create_app(db_path=None):
    """Build the Flask app. Tests pass a different db_path to use a temp database."""
    if db_path is None:
        db_path = os.environ.get("DB_PATH") or db.DEFAULT_DB_PATH

    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    # --- Password gate (only switched on when APP_PASSWORD is set) ---
    password = os.environ.get("APP_PASSWORD", "")
    secret_key = os.environ.get("SECRET_KEY", "")
    if password and not secret_key:
        # Without a fixed key, everyone would be logged out on every restart,
        # and a missing setting is better caught now than on the phone later.
        raise RuntimeError("APP_PASSWORD is set, so SECRET_KEY must be set too. See DEPLOY.md.")
    # Locally (no password) a random key is fine: the login cookie isn't used
    app.config["SECRET_KEY"] = secret_key or secrets.token_hex(32)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)  # stay logged in on your phone
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # other websites can't post forms as you
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"

    app.jinja_env.globals["metric_or_none"] = metric_or_none

    db.init_db(db_path)
    db.import_seed_data(db_path)  # only does anything when there are no recipes yet

    def get_recipe_or_404(recipe_id):
        recipe = db.get_recipe(recipe_id, db_path=db_path)
        if recipe is None:
            abort(404)  # shows Flask's standard "Not Found" page
        return recipe

    # Read the picked recipes from the URL: ?recipe=1&recipe=3 says which were
    # ticked, and ?servings_1=8 says how many servings for recipe 1. Ids that
    # aren't numbers, don't exist, or appear twice are skipped.
    def read_picks(args):
        picks = []
        seen = set()
        for text in args.getlist("recipe"):
            try:
                recipe_id = int(text)
            except ValueError:
                continue
            recipe = db.get_recipe(recipe_id, db_path=db_path)
            if recipe is None or recipe_id in seen:
                continue
            seen.add(recipe_id)
            servings = requested_servings(args.get(f"servings_{recipe_id}"), recipe["servings"])
            picks.append((recipe, servings))
        return picks

    # Values every page can use:
    #   password_on: show the "Log out" link only when there's a password
    #   this_week:   {recipe_id: servings} for the "This week (N)" bar and the
    #                "Add to this week" buttons (None on the login page)
    #   protein_names, meal_types: for showing and editing labels
    @app.context_processor
    def page_info():
        logged_in = not password or session.get("logged_in")
        return {
            "password_on": bool(password),
            "this_week": db.plan_servings(db_path=db_path) if logged_in else None,
            "protein_names": labels.PROTEINS,
            "meal_types": labels.MEAL_TYPES,
        }

    # Runs before every page. With a password set, anyone not logged in is sent
    # to /login (the login page itself and the CSS are let through).
    @app.before_request
    def require_login():
        if not password or request.endpoint in ("login", "static"):
            return None
        if session.get("logged_in"):
            return None
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not password:
            return redirect(url_for("index"))  # no password set: nothing to log in to
        next_page = request.values.get("next", "")
        error = ""
        if request.method == "POST":
            given = request.form.get("password", "")
            # compare_digest takes the same time whether the first letter or the
            # last one is wrong, so timing can't leak the password bit by bit
            if hmac.compare_digest(given.encode("utf-8"), password.encode("utf-8")):
                session.clear()
                session["logged_in"] = True
                session.permanent = True   # keep the cookie for 30 days
                return redirect(safe_next(next_page))
            error = "That password isn't right. Try again."
        return render_template("login.html", error=error, next_page=next_page), (401 if error else 200)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login") if password else url_for("index"))

    # --- Routes: each @app.route connects a URL to the function that handles it ---

    # Home page with search, protein chips and tag filter. The filter lives in
    # the URL, e.g. /?q=chick&protein=chicken&tag=dinner, so it survives a
    # refresh and can be bookmarked.
    @app.route("/")
    def index():
        query = request.args.get("q", "").strip()
        active_tags = db.parse_tags(",".join(request.args.getlist("tag")))
        protein = request.args.get("protein", "")
        if protein not in labels.PROTEINS:
            protein = ""   # unknown value (old or typed link): show all

        # Search and tags first; the chip counts say how many of THESE
        # have each protein, so a chip's number is what you get by tapping it
        matches = db.search_recipes(query, active_tags, db_path=db_path)
        protein_counts = labels.count_proteins(matches)
        recipes = [r for r in matches if protein in r["proteins"]] if protein else matches

        # Show active tags first (so they're visible when the pills scroll
        # sideways on a phone), then the rest. An active tag that no recipe uses
        # any more (old bookmark) still gets a pill so it can be clicked off.
        other_tags = [t for t in db.list_tags(db_path=db_path) if t not in active_tags]

        # Each pill is a link to this page with that one tag switched on or off
        def toggle_link(tag):
            if tag in active_tags:
                new_tags = [t for t in active_tags if t != tag]
            else:
                new_tags = active_tags + [tag]
            return url_for("index", q=query or None, protein=protein or None, tag=new_tags)

        # Each protein chip keeps the search and tags; "" is the "All" chip
        def protein_link(key):
            return url_for("index", q=query or None, protein=key or None, tag=active_tags)

        return render_template(
            "index.html",
            recipes=recipes,
            total=db.count_recipes(db_path=db_path),
            query=query,
            active_tags=active_tags,
            all_tags=active_tags + other_tags,
            toggle_link=toggle_link,
            protein=protein,
            protein_counts=protein_counts,
            match_total=len(matches),
            protein_link=protein_link,
            filtering=bool(query or active_tags or protein),
            # After importing several recipes: /?imported=3&skipped=1 shows a note
            imported=request.args.get("imported", type=int),
            skipped=request.args.get("skipped", type=int),
        )

    @app.route("/recipes/<int:recipe_id>")
    def recipe_detail(recipe_id):
        recipe = get_recipe_or_404(recipe_id)
        servings = requested_servings(request.args.get("servings"), recipe["servings"])
        system = requested_units(request.args.get("units"))

        # Scaling and unit conversion only change what's shown on this page,
        # never what's saved. See units.show_ingredient for the rules.
        factor = Fraction(servings, recipe["servings"])
        ingredients = []
        for ing in recipe["ingredients"]:
            amount, unit = units.show_ingredient(ing["amount"], ing["unit"], factor, system)
            ingredients.append(dict(ing, amount=amount, unit=unit))

        return render_template(
            "recipe_detail.html",
            recipe=recipe,
            servings=servings,
            ingredients=ingredients,
            max_servings=MAX_SERVINGS,
            units=system,
            units_links=units_links("recipe_detail", recipe_id=recipe_id),
        )

    # GET shows the empty form; POST is what happens when you press "Save"
    @app.route("/recipes/new", methods=["GET", "POST"])
    def recipe_new():
        if request.method == "POST":
            recipe, errors = read_recipe_form(request.form)
            if not errors:
                recipe_id = db.create_recipe(**recipe, db_path=db_path)
                return redirect(url_for("recipe_detail", recipe_id=recipe_id))
            # Something was wrong: show the form again with what they typed
            return render_template("recipe_form.html", recipe=recipe, errors=errors), 400

        blank = {"name": "", "servings": 4, "ingredients": [], "steps": "", "tags": [],
                 "proteins": [], "meal_type": ""}
        return render_template("recipe_form.html", recipe=blank, errors=[])

    @app.route("/recipes/<int:recipe_id>/edit", methods=["GET", "POST"])
    def recipe_edit(recipe_id):
        existing = get_recipe_or_404(recipe_id)
        if request.method == "POST":
            recipe, errors = read_recipe_form(request.form)
            if not errors:
                # A label you changed is now yours. One you left as it was is
                # passed as None, so a guessed label is guessed again from the
                # new ingredients. "Guess again" ([] and "") resets both.
                if request.form.get("guess_labels"):
                    recipe["proteins"], recipe["meal_type"] = [], ""
                else:
                    if recipe["proteins"] == existing["proteins"]:
                        recipe["proteins"] = None
                    if recipe["meal_type"] == existing["meal_type"]:
                        recipe["meal_type"] = None
                db.update_recipe(recipe_id, **recipe, db_path=db_path)
                return redirect(url_for("recipe_detail", recipe_id=recipe_id))
            recipe["id"] = recipe_id
            return render_template("recipe_form.html", recipe=recipe, errors=errors), 400

        return render_template("recipe_form.html", recipe=existing, errors=[])

    # GET only shows "Are you sure?"; the actual delete needs a POST from that page's button
    @app.route("/recipes/<int:recipe_id>/delete", methods=["GET", "POST"])
    def recipe_delete(recipe_id):
        recipe = get_recipe_or_404(recipe_id)
        if request.method == "POST":
            db.delete_recipe(recipe_id, db_path=db_path)
            return redirect(url_for("index"))
        return render_template("recipe_delete.html", recipe=recipe)

    # --- Import: paste JSON or give a link, check the preview, then save ---
    # Nothing is saved until the Save button. The preview carries the recipes
    # to the save step in a hidden form field, and they're checked again there.

    def import_page(status=200, **values):
        page = {
            "json_text": "", "url": "", "errors": [], "url_error": "",
            "preview": None, "notes": [], "prompt": importer.CLAUDE_PROMPT,
        }
        page.update(values)
        return render_template("import.html", **page), status

    def preview_page(recipes, json_text, notes=(), url="", errors=(), status=200):
        existing = [r["name"] for r in db.list_recipes(db_path=db_path)]
        return import_page(
            status,
            preview=recipes,
            duplicates=importer.find_duplicates(recipes, existing),
            recipes_json=importer.recipes_to_json(recipes),
            json_text=json_text,
            notes=list(notes),
            url=url,
            errors=list(errors),
        )

    @app.route("/import")
    def import_recipes():
        return import_page()

    # Option A: pasted JSON
    @app.route("/import/preview", methods=["POST"])
    def import_preview():
        json_text = request.form.get("json_text", "")
        recipes, errors = importer.parse_json_text(json_text)
        if errors:
            return import_page(400, json_text=json_text, errors=errors)
        return preview_page(recipes, json_text)

    # Option B: a link to a recipe page. The JSON box is filled in too, so
    # you can fix anything the page got wrong and preview again.
    @app.route("/import/url", methods=["POST"])
    def import_url():
        url = request.form.get("url", "").strip()
        try:
            recipe, notes = importer.recipe_from_url(url)
        except importer.ImportFailed as e:
            return import_page(400, url=url, url_error=f"{e} {importer.URL_HELP}")
        return preview_page([recipe], importer.recipes_to_json([recipe]), notes, url)

    @app.route("/import/save", methods=["POST"])
    def import_save():
        recipes_json = request.form.get("recipes_json", "")
        recipes, errors = importer.parse_json_text(recipes_json)
        if errors:
            return import_page(400, errors=errors)
        # Duplicates are skipped unless their "Save anyway" box was ticked
        save_anyway = {int(p) for p in request.form.getlist("save_anyway") if p.isdigit()}
        saved_ids, skipped = importer.save_recipes(recipes, save_anyway, db_path=db_path)

        if not saved_ids:
            message = ("Nothing was saved: a recipe with this name already exists."
                       if len(recipes) == 1 else
                       "Nothing was saved: all of these recipes already exist.")
            message += ' Tick "Save anyway" to save a copy.'
            return preview_page(recipes, recipes_json, errors=[message], status=400)
        if len(saved_ids) == 1:
            return redirect(url_for("recipe_detail", recipe_id=saved_ids[0]))
        return redirect(url_for("index", imported=len(saved_ids), skipped=len(skipped) or None))

    # Download every recipe as one JSON file, in the same format the import
    # page reads, so it works as a backup and to move recipes between copies.
    @app.route("/export")
    def export_recipes():
        recipes = [db.get_recipe(r["id"], db_path=db_path) for r in db.list_recipes(db_path=db_path)]
        data = [importer.to_json_format(r) for r in recipes]
        text = json.dumps(data, indent=2, ensure_ascii=False)
        filename = f"recipes-{date.today().isoformat()}.json"
        return Response(
            text,
            mimetype="application/json",
            # "attachment" makes the browser save it as a file instead of showing it
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # --- This week's plan, saved in the database ---
    # Buttons on the recipe cards and pages post here, then come back to the
    # page they were on (the "next" field), so no JavaScript is needed.

    def back_to_page():
        return redirect(safe_next(request.form.get("next", "")))

    @app.route("/plan/add/<int:recipe_id>", methods=["POST"])
    def plan_add(recipe_id):
        recipe = get_recipe_or_404(recipe_id)
        # The recipe page sends the servings you scaled it to
        servings = requested_servings(request.form.get("servings"), recipe["servings"])
        db.add_to_plan(recipe_id, servings, db_path=db_path)
        return back_to_page()

    @app.route("/plan/remove/<int:recipe_id>", methods=["POST"])
    def plan_remove(recipe_id):
        db.remove_from_plan(recipe_id, db_path=db_path)
        return back_to_page()

    @app.route("/plan/clear", methods=["POST"])
    def plan_clear():
        db.clear_plan(db_path=db_path)
        return redirect(url_for("plan"))

    # The plan page's "Save" buttons: one stays here, one goes on to the list
    @app.route("/plan/servings", methods=["POST"])
    def plan_save_servings():
        for recipe_id, servings in db.plan_servings(db_path=db_path).items():
            new = requested_servings(request.form.get(f"servings_{recipe_id}"), servings)
            db.set_plan_servings(recipe_id, new, db_path=db_path)
        units = metric_or_none(request.form.get("units"))
        if request.form.get("then") == "grocery":
            return redirect(url_for("grocery_list", units=units))
        return redirect(url_for("plan", units=units))

    # Before the plan was saved, it lived in links like /plan?recipe=2&servings_2=8.
    # Those links still work: the page shows the saved plan plus a button to
    # add the link's recipes to it.
    @app.route("/plan/load", methods=["POST"])
    def plan_load_old_link():
        for recipe, servings in read_picks(request.form):
            db.add_to_plan(recipe["id"], servings, db_path=db_path)
            db.set_plan_servings(recipe["id"], servings, db_path=db_path)
        return redirect(url_for("plan"))

    @app.route("/plan")
    def plan():
        return render_template(
            "plan.html",
            picks=db.get_plan(db_path=db_path),
            old_picks=read_picks(request.args),
            max_servings=MAX_SERVINGS,
            units=requested_units(request.args.get("units")),
        )

    # The merged shopping list for this week's plan. Worked out fresh from
    # the saved plan each time, so it always matches the plan page.
    @app.route("/grocery")
    def grocery_list():
        picks = db.get_plan(db_path=db_path)
        system = requested_units(request.args.get("units"))
        groups = grocery.group_by_aisle(grocery.merge_ingredients(picks, system))
        return render_template(
            "grocery.html",
            picks=picks,
            old_picks=read_picks(request.args),
            # Names this exact plan, so ticks are remembered per plan: change a
            # recipe or its servings and the list starts fresh (see grocery.js)
            plan_key=",".join(f"{recipe['id']}x{servings}" for recipe, servings in picks),
            groups=groups,
            list_text=grocery.grocery_text(groups),
            units=system,
            units_links=units_links("grocery_list"),
        )

    return app


if __name__ == "__main__":
    # Only for running on your own computer. The hosted copy loads the app
    # through wsgi.py instead, so this line (and debug mode) never runs there.
    create_app().run(debug=True, port=int(os.environ.get("PORT", 5000)))
