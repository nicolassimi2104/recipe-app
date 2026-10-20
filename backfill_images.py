"""One-time helper: add photos to recipes you already have.

Run it from the recipe-app folder (with the venv on):  python backfill_images.py

For each recipe with no photo it looks for a web page to read one from:
  1. the recipe's own saved link (recipes imported from now on keep one), or
  2. the "Fresh finds" idea it was imported from.
Recipes typed in by hand have no page to read, so add a photo link on their
Edit page instead. Safe to run again: recipes that have a photo are skipped.
"""

import re

from recipe_scrapers import scrape_html

import db
import importer

OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I)


def image_from_page(url):
    """Photo link from a recipe page, or "" if it can't be read."""
    try:
        html = importer.fetch_html(importer.check_url(url))
    except importer.ImportFailed:
        return ""
    try:
        found = importer.image_from_scraper(scrape_html(html, org_url=url, supported_only=False))
        if found:
            return found
    except Exception:
        pass   # the page has no recipe data; try the plain page picture below
    match = OG_IMAGE.search(html)
    return importer.clean_link(match.group(1)) if match else ""


def backfill(db_path=db.DEFAULT_DB_PATH, find_image=image_from_page):
    """Fill in missing photos. Returns (recipes_updated, recipes_without_a_page)."""
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT r.id, r.source_url AS own_url, s.url AS find_url, s.image AS find_image"
            " FROM recipes r LEFT JOIN suggestions s ON s.recipe_id = r.id"
            " WHERE r.image = ''"
        ).fetchall()
    finally:
        conn.close()

    updated = no_page = 0
    for row in rows:
        url = row["own_url"] or row["find_url"] or ""
        image = importer.clean_link(row["find_image"]) or (find_image(url) if url else "")
        if not url and not image:
            no_page += 1
            continue
        if image:
            conn = db.get_connection(db_path)
            try:
                with conn:
                    conn.execute("UPDATE recipes SET image = ?, source_url = CASE WHEN source_url = '' THEN ? ELSE source_url END WHERE id = ?",
                                 (image, url, row["id"]))
            finally:
                conn.close()
            updated += 1
    return updated, no_page


if __name__ == "__main__":
    db.init_db()
    done, skipped = backfill()
    print(f"Added photos to {done} recipe(s). {skipped} recipe(s) have no page to read one from.")
