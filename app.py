"""Recipe app: the Flask web server.

Run with:  python app.py   (then open http://localhost:5000)

Settings come from environment variables, so nothing secret is in the code.
None of them are needed for local use:
    APP_PASSWORD  if set, every page asks for this password first (for the hosted copy)
    SECRET_KEY    signs the login cookie; required when APP_PASSWORD is set
    DB_PATH       where the SQLite file lives (default: recipes.db next to this file)
    PORT          port for "python app.py" (default: 5000)
    SESSION_COOKIE_SECURE=1  only send the login cookie over https (set this when hosted)
    DATABASE_URL  on Render: keep a copy of the database in Postgres (see cloud_save.py)
    RESTORE_FILE  on Render: JSON backup to load if Postgres is empty (see RENDER.md)
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

import cloud_save
import db
import grocery
import importer
import labels
import pairing
import suggestions
import units

# Upper limit for the "scale to" box, so a silly number can't make a huge page
MAX_SERVINGS = 1000
# Upper limit for "keeps N days in the fridge"
MAX_FRIDGE_DAYS = 60
# Add the starter side dishes (sides.json) on startup. Most tests switch
# this off so they keep working with just the 4 starter recipes.
ADD_STARTER_SIDES = True


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


HOME_LATEST = 8   # recipes shown on the home page when none are starred


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

    # Fridge days are optional: blank means "don't know"
    fridge_text = form.get("fridge_days", "").strip()
    fridge_days = int(fridge_text) if fridge_text.isdigit() else None
    if fridge_text and (fridge_days is None or fridge_days > MAX_FRIDGE_DAYS):
        errors.append(f"Fridge days must be a whole number from 0 to {MAX_FRIDGE_DAYS}, or blank.")

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
        "cuisine": labels.clean_cuisine(form.get("cuisine", "")),
        "side_type": labels.clean_side_type(form.get("side_type", "")),
        "fridge_days": fridge_text if errors else fridge_days,
        "image": importer.clean_link(form.get("image", "")),
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

    # On Render the files are wiped on every restart, so the database is also
    # kept in Postgres (see cloud_save.py). Locally there's no DATABASE_URL
    # and cloud is None, so this is all skipped.
    cloud = cloud_save.store_from_env()
    if cloud:
        restored = cloud_save.restore_on_startup(db_path, cloud)
        app.logger.warning("Recipes restored from: %s", restored)

    db.init_db(db_path)
    db.import_seed_data(db_path)  # only does anything when there are no recipes yet
    if ADD_STARTER_SIDES:
        db.seed_side_bank(db_path)  # the starter side dishes, added only once ever

    if cloud:
        # A brand-new app (nothing restored) only has the sample recipes, so
        # don't save yet: that way a backup file added a bit later still
        # gets loaded on the next restart
        if restored != "nothing":
            cloud_save.save_now(db_path, cloud)

        # Every change in the app is a submitted form (POST), so save a copy
        # after each one that worked
        @app.after_request
        def save_to_cloud(response):
            if request.method == "POST" and response.status_code < 400:
                try:
                    cloud_save.save_now(db_path, cloud)
                except Exception:
                    # The change is still in the local file and goes along
                    # with the next save; don't show an error page for it
                    app.logger.exception("Couldn't save the database copy to Postgres")
            return response

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
            "cuisines": labels.CUISINES,
            "side_types": labels.SIDE_TYPES,
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
        filtering_now = bool(query or active_tags or protein)

        # Home page with no filters: just your favorites (or the newest 8 if you
        # haven't starred any). Any search, tag or protein looks at everything.
        showing_all = request.args.get("all") == "1"
        home_note = ""
        if not filtering_now and not showing_all and matches:
            favorites = [r for r in matches if r["favorite"]]
            if favorites:
                recipes, home_note = favorites, "favorites"
            elif len(matches) > HOME_LATEST:
                recipes, home_note = sorted(matches, key=lambda r: -r["id"])[:HOME_LATEST], "latest"

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

        # Fresh finds: if they're over a week old, read the feeds again in the
        # background (the page doesn't wait). The strip is hidden while filtering.
        try:
            suggestions.refresh_if_stale(db_path)
        except Exception:
            pass   # a refresh problem must never break the home page
        filtering = bool(query or active_tags or protein)

        return render_template(
            "index.html",
            **fresh_finds_values(show=not filtering),
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
            filtering=filtering,
            home_note=home_note,
            showing_all=showing_all,
            # After importing several recipes: /?imported=3&skipped=1 shows a note
            imported=request.args.get("imported", type=int),
            skipped=request.args.get("skipped", type=int),
        )

    # Values for the Fresh finds strip (templates/_fresh_finds.html).
    # After a failed import the home page gets ?find_failed=<id> (the page had
    # no recipe, so it was dismissed) or ?find_offline=<id> (couldn't reach it).
    def fresh_finds_values(show=True):
        def note_about(param):
            suggestion_id = request.args.get(param, type=int)
            return db.get_suggestion(suggestion_id, db_path=db_path) if suggestion_id else None
        return {
            "finds": db.new_suggestions(suggestions.STRIP_SIZE, db_path=db_path) if show else [],
            "finds_refreshing": suggestions.is_refreshing(db_path),
            "find_failed": note_about("find_failed"),
            "find_offline": note_about("find_offline"),
        }

    # Just the strip, so the home page can fill it in once a first refresh
    # finishes, without reloading the whole page (static/fresh_finds.js)
    @app.route("/fresh-finds")
    def fresh_finds_strip():
        return render_template("_fresh_finds.html", **fresh_finds_values())

    # One click: read the recipe from the site, save it (labels are guessed
    # as it's saved) and open it
    @app.route("/fresh-finds/<int:suggestion_id>/import", methods=["POST"])
    def fresh_find_import(suggestion_id):
        suggestion = db.get_suggestion(suggestion_id, db_path=db_path)
        if suggestion is None:
            abort(404)
        # A double click: the first click already saved it
        if suggestion["status"] == "imported" and suggestion["recipe_id"]:
            return redirect(url_for("recipe_detail", recipe_id=suggestion["recipe_id"]))
        try:
            recipe_id = suggestions.import_suggestion(suggestion, db_path)
        except importer.SiteUnreachable:
            return redirect(url_for("index", find_offline=suggestion_id, _anchor="fresh-finds"))
        except importer.ImportFailed:
            return redirect(url_for("index", find_failed=suggestion_id, _anchor="fresh-finds"))
        return redirect(url_for("recipe_detail", recipe_id=recipe_id, found=suggestion_id))

    # Dismissed ones never come back; the next one slides into the strip
    @app.route("/fresh-finds/<int:suggestion_id>/dismiss", methods=["POST"])
    def fresh_find_dismiss(suggestion_id):
        if db.get_suggestion(suggestion_id, db_path=db_path) is None:
            abort(404)
        db.set_suggestion_status(suggestion_id, "dismissed", db_path=db_path)
        return redirect(url_for("index", _anchor="fresh-finds"))

    # Just imported from Fresh finds (?found=<suggestion id>): the recipe page
    # says where it came from and has a one-click Delete. Only when that
    # suggestion really became this recipe.
    def found_from(recipe_id):
        suggestion_id = request.args.get("found", type=int)
        suggestion = db.get_suggestion(suggestion_id, db_path=db_path) if suggestion_id else None
        return suggestion if suggestion and suggestion["recipe_id"] == recipe_id else None

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
            found=found_from(recipe_id),
            **side_suggestions(recipe, servings, system),
        )

    # "Sides that fit" on a main dish's page (the rules are in pairing.py).
    # ?shuffle=N shows set number N; the Shuffle button links to the next one.
    def side_suggestions(recipe, servings, system):
        if recipe["meal_type"] != "main":
            return {"show_sides": False}
        shuffle = request.args.get("shuffle", type=int) or 0
        if shuffle < 0:
            shuffle = 0
        sides = db.list_sides(db_path=db_path)
        _, reason = pairing.wanted_side_types(recipe)
        return {
            "show_sides": True,
            "sides": pairing.pick_sides(recipe, sides, shuffle),
            "sides_reason": pairing.REASONS[reason],
            # Keep the scaling and units when shuffling
            "shuffle_link": url_for(
                "recipe_detail", recipe_id=recipe["id"],
                servings=servings if servings != recipe["servings"] else None,
                units=metric_or_none(system), shuffle=shuffle + 1, _anchor="sides",
            ) if len(sides) > pairing.HOW_MANY else None,
        }

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
                 "proteins": [], "meal_type": "", "cuisine": "", "side_type": "",
                 "fridge_days": None}
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
                    recipe["cuisine"], recipe["side_type"] = "", ""
                else:
                    if recipe["proteins"] == existing["proteins"]:
                        recipe["proteins"] = None
                    if recipe["meal_type"] == existing["meal_type"]:
                        recipe["meal_type"] = None
                    if recipe["cuisine"] == existing["cuisine"]:
                        recipe["cuisine"] = None
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

    @app.route("/favorite/<int:recipe_id>", methods=["POST"])
    def favorite_toggle(recipe_id):
        recipe = get_recipe_or_404(recipe_id)
        db.set_favorite(recipe_id, not recipe["favorite"], db_path=db_path)
        return back_to_page()

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
