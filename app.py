"""Recipe app: the Flask web server.

Run with:  python app.py   (then open http://localhost:5000)
"""

from fractions import Fraction
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, url_for

import db
import grocery
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

    @app.route("/")
    def index():
        recipes = db.list_recipes(db_path=db_path)
        return render_template("index.html", recipes=recipes)

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
