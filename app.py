"""Recipe app: the Flask web server.

Run with:  python app.py   (then open http://localhost:5000)
"""

from fractions import Fraction
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, url_for

import db
import grocery
import importer
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
    }
    return recipe, errors


def create_app(db_path=db.DEFAULT_DB_PATH):
    """Build the Flask app. Tests pass a different db_path to use a temp database."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    # For links in templates: url_for leaves out values that are None, so this
    # adds ?units=metric only when metric is on (US is the default).
    app.jinja_env.globals["metric_or_none"] = lambda system: "metric" if system == "metric" else None

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

    # --- Routes: each @app.route connects a URL to the function that handles it ---

    # Home page with search and tag filter. The filter lives in the URL,
    # e.g. /?q=chick&tag=dinner&tag=quick, so it survives a refresh and can be bookmarked.
    @app.route("/")
    def index():
        query = request.args.get("q", "").strip()
        active_tags = db.parse_tags(",".join(request.args.getlist("tag")))
        recipes = db.search_recipes(query, active_tags, db_path=db_path)

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
            return url_for("index", q=query or None, tag=new_tags)

        return render_template(
            "index.html",
            recipes=recipes,
            total=db.count_recipes(db_path=db_path),
            query=query,
            active_tags=active_tags,
            all_tags=active_tags + other_tags,
            toggle_link=toggle_link,
            filtering=bool(query or active_tags),
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

        blank = {"name": "", "servings": 4, "ingredients": [], "steps": "", "tags": []}
        return render_template("recipe_form.html", recipe=blank, errors=[])

    @app.route("/recipes/<int:recipe_id>/edit", methods=["GET", "POST"])
    def recipe_edit(recipe_id):
        existing = get_recipe_or_404(recipe_id)
        if request.method == "POST":
            recipe, errors = read_recipe_form(request.form)
            if not errors:
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

    # Pick recipes for the week. Coming back from the grocery list keeps your
    # ticks and servings, because the same ?recipe=... values are in the URL.
    @app.route("/plan")
    def plan():
        recipes = db.list_recipes(db_path=db_path)
        picked = {recipe["id"]: servings for recipe, servings in read_picks(request.args)}
        return render_template(
            "plan.html",
            recipes=recipes,
            picked=picked,
            max_servings=MAX_SERVINGS,
            units=requested_units(request.args.get("units")),
        )

    # The merged shopping list for the picked recipes. Nothing is saved:
    # the list is worked out fresh from the URL each time.
    @app.route("/grocery")
    def grocery_list():
        picks = read_picks(request.args)
        system = requested_units(request.args.get("units"))
        groups = grocery.group_by_aisle(grocery.merge_ingredients(picks, system))
        return render_template(
            "grocery.html",
            picks=picks,
            groups=groups,
            list_text=grocery.grocery_text(groups),
            units=system,
            units_links=units_links("grocery_list"),
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5000)
