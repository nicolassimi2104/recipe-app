"""Entry point for the hosted copy of the app.

Web servers (PythonAnywhere, or gunicorn with "gunicorn wsgi:app") import
`app` from this file. Unlike "python app.py", this never turns on debug mode,
which must stay off on the internet because its error page can run code.

Settings (APP_PASSWORD, SECRET_KEY, DB_PATH...) come from environment
variables. If there's a .env file next to this one, it's read first; that
file holds the secrets on the server and is never committed (see .gitignore).
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app import create_app  # noqa: E402  (import after the settings are loaded)

app = create_app()
