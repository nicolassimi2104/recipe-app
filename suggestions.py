"""Fresh finds: recipe ideas from recipe-site feeds, shown on the home page.

When the home page opens and the newest suggestion is over a week old (or
there are none), the feeds below are read in the background, so the page
never waits for them. Each new post is saved in the suggestions table, and
the home page shows the newest three. Import saves the recipe through the
same link-import code as the Import page (importer.py).

No Flask code here; the database parts are in db.py.
"""

import html
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import db
import importer

# ---------------------------------------------------------------------------
# The feeds. Edit freely: (name shown on the cards, RSS or Atom feed link).
# Each one was checked to load and to have recipes that import cleanly.
# ---------------------------------------------------------------------------
FEEDS = [
    ("Budget Bytes", "https://www.budgetbytes.com/feed/"),
    ("Cookie and Kate", "https://cookieandkate.com/feed/"),        # vegetarian
    ("RecipeTin Eats", "https://www.recipetineats.com/feed/"),
    ("Smitten Kitchen", "https://smittenkitchen.com/feed/"),
    ("Once Upon a Chef", "https://www.onceuponachef.com/feed"),
    ("Minimalist Baker", "https://minimalistbaker.com/feed/"),     # vegan
    ("Gimme Some Oven", "https://www.gimmesomeoven.com/feed/"),
]

# Read the feeds again when the newest suggestion is older than this
STALE_AFTER = timedelta(days=7)
# After a try (say the internet was down), wait this long before the next one
RETRY_AFTER = timedelta(hours=1)
# Seconds to wait for one feed. They're all read at the same time.
FEED_TIMEOUT = 4
# Feeds are small; stop reading at 2 MB so a broken one can't jam the app
MAX_FEED_BYTES = 2 * 1024 * 1024
# Only keep the newest few posts from each feed
MAX_PER_FEED = 10
# How many cards the home page shows
STRIP_SIZE = 3

# Tests set this to False so a refresh finishes before the page is checked
RUN_IN_BACKGROUND = True


class FeedError(Exception):
    """A feed couldn't be downloaded or read."""


# ---------------------------------------------------------------------------
# Reading a feed
# ---------------------------------------------------------------------------

def fetch_feed(url, timeout=FEED_TIMEOUT):
    """Download a feed and return its raw bytes. Raises FeedError on any problem."""
    request = urllib.request.Request(url, headers=importer.REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
    except Exception as e:   # no internet, too slow, site error: all mean "skip this feed"
        raise FeedError(f"Couldn't download {url}: {e}") from e
    if len(raw) > MAX_FEED_BYTES:
        raise FeedError(f"{url} is too big to be a feed")
    return raw


# XML names with their "namespace" in front, as ElementTree spells them
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def parse_feed(raw, source):
    """Turn feed XML (RSS or Atom) into a list of suggestion dicts:
        {"title": ..., "url": ..., "source": ..., "image": ... or ""}
    Posts without a title or a web link are skipped. Raises FeedError if
    the text isn't a feed at all.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise FeedError(f"{source}: not a readable feed ({e})") from e

    items = root.findall("./channel/item") or root.findall(f"{ATOM}entry")
    found = []
    for item in items[:MAX_PER_FEED]:
        if item.tag == "item":   # RSS
            title = item.findtext("title")
            link = item.findtext("link")
            body = (item.findtext(CONTENT) or "") + (item.findtext("description") or "")
        else:                    # Atom: the link is in href, the post in content
            title = item.findtext(f"{ATOM}title")
            link = _atom_link(item)
            body = (item.findtext(f"{ATOM}content") or "") + (item.findtext(f"{ATOM}summary") or "")
        title = clean_title(title)
        url = clean_url(link)
        if title and url:
            found.append({"title": title, "url": url, "source": source,
                          "image": _find_image(item, body)})
    return found


def _atom_link(entry):
    for link in entry.findall(f"{ATOM}link"):
        if link.get("rel", "alternate") == "alternate":
            return link.get("href")
    return None


# A picture for the card: the feed's own media tags first, then the first
# <img> in the post. Only web links are kept.
def _find_image(item, body):
    candidates = []
    for tag in (f"{MEDIA}content", f"{MEDIA}thumbnail", "enclosure"):
        for element in item.iter(tag):
            if element.get("medium") == "image" or "image" in element.get("type", "image"):
                candidates.append(element.get("url"))
    match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", body)
    if match:
        candidates.append(html.unescape(match.group(1)))
    for url in candidates:
        if url and urlparse(url).scheme in ("http", "https"):
            return url.strip()
    return ""


def clean_title(text):
    """"Jo&#8217;s <b>Chili</b>" -> "Jo's Chili": no tags, no codes, single spaces."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return " ".join(html.unescape(text).split())


def clean_url(url):
    """The trimmed web link, without tracking bits like ?utm_source=rss, so
    the same post linked twice counts as one. None if it isn't a web link."""
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    return urlunparse(parts._replace(query=urlencode(query), fragment=""))


# ---------------------------------------------------------------------------
# Refreshing
# ---------------------------------------------------------------------------

def now_text(now=None):
    """The time as text for the database, e.g. "2026-10-18T09:30:00" (UTC)."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S")


def is_stale(db_path, now=None):
    """True when there are no suggestions, or the newest is over STALE_AFTER old."""
    newest = db.newest_suggestion_time(db_path=db_path)
    if newest is None:
        return True
    newest = datetime.fromisoformat(newest).replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - newest > STALE_AFTER


def refresh(db_path, fetch=None, now=None):
    """Read every feed and save the new posts. Returns how many were added.

    A feed that fails is skipped. Posts already saved (new, imported or
    dismissed) are skipped, and so are ones named like a recipe you have.
    fetch is the download function (tests pass a fake one).
    """
    fetch = fetch or fetch_feed
    def read_one(feed):
        source, url = feed
        try:
            return parse_feed(fetch(url), source)
        except Exception:
            return []   # one broken feed never stops the others

    # Read all feeds at the same time, so a slow one doesn't hold up the rest
    with ThreadPoolExecutor(max_workers=len(FEEDS) or 1) as pool:
        per_feed = list(pool.map(read_one, FEEDS))

    # Take one post from each feed in turn, so the cards mix sites
    mixed = []
    for position in range(max((len(posts) for posts in per_feed), default=0)):
        mixed += [posts[position] for posts in per_feed if position < len(posts)]

    have = {importer.name_key(r["name"]) for r in db.list_recipes(db_path=db_path)}
    mixed = [s for s in mixed if importer.name_key(s["title"]) not in have]
    return db.add_suggestions(mixed, now_text(now), db_path=db_path)


# Which databases are being refreshed right now, and when each was last
# tried. Kept in memory: it only stops the app asking twice at once, or
# every page load while the internet is down.
_lock = threading.Lock()
_running = set()
_last_try = {}


def is_refreshing(db_path):
    with _lock:
        return str(db_path) in _running


def refresh_if_stale(db_path, fetch=None, now=None):
    """Called when the home page opens. Starts a refresh if the suggestions
    are stale, and returns right away (the reading happens in the
    background). Returns True if a refresh was started.
    """
    key = str(db_path)
    clock = now or datetime.now(timezone.utc)
    if not is_stale(db_path, clock):
        return False
    with _lock:
        last = _last_try.get(key)
        if key in _running or (last and clock - last < RETRY_AFTER):
            return False
        _running.add(key)
        _last_try[key] = clock

    def work():
        try:
            refresh(db_path, fetch, now)
        except Exception:
            pass   # never let a refresh problem reach the page
        finally:
            with _lock:
                _running.discard(key)

    if RUN_IN_BACKGROUND:
        # daemon=True: a refresh still running never stops the app from closing
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return True


# ---------------------------------------------------------------------------
# Import and dismiss
# ---------------------------------------------------------------------------

def import_suggestion(suggestion, db_path):
    """Save a suggestion as a recipe and return the new recipe's id.

    Labels (protein and meal type) are guessed when it's saved, as for any
    import. If the page has no recipe we can read, the suggestion is marked
    dismissed and importer.ImportFailed is raised. If the site can't be
    reached (say the internet is down), it stays, so you can try again.
    """
    try:
        recipe, _notes = importer.recipe_from_url(suggestion["url"])
    except importer.SiteUnreachable:
        raise
    except importer.ImportFailed:
        db.set_suggestion_status(suggestion["id"], "dismissed", db_path=db_path)
        raise
    recipe_id = db.create_recipe(**recipe, db_path=db_path)
    db.set_suggestion_status(suggestion["id"], "imported", recipe_id=recipe_id, db_path=db_path)
    return recipe_id
