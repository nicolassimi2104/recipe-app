"""Recipe app: the Flask web server.

Run with:  python app.py   (then open http://localhost:5000)
"""

from flask import Flask, render_template

import db


def create_app(db_path=db.DEFAULT_DB_PATH):
    """Build the Flask app. Tests pass a different db_path to use a temp database."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    db.init_db(db_path)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5000)
