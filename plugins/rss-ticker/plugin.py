# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""RSS Ticker: headlines from your feeds rotating on the bar, the full list in the flyout.

feeds.py fetches and parses (RSS 2.0, Atom 1.0, RSS 1.0/RDF), views.py renders;
this file is the glue: settings, the cache in app.data_dir, one refresh worker
at a time, the flyout actions and the agent commands.
"""

import threading
import time
from datetime import UTC, datetime

import feeds
import views
from smabar_sdk import Plugin

app = Plugin()
TILE = "news"
CACHE_FILE = "feeds.json"
TICK_SECONDS = 60
LATEST_DEFAULT = 10
# setting: (default, minimum, maximum)
NUMBERS = {"refreshMinutes": (15, 5, 1440), "tileItems": (5, 1, 20), "maxPerFeed": (20, 1, 100)}
URL_SCHEMA = {
    "type": "object",
    "properties": {"url": {"type": "string", "description": "Absolute http(s) address of the feed"}},
    "required": ["url"],
    "additionalProperties": False,
}
FEEDS_SCHEMA = {
    "type": "object",
    "properties": {
        "changed": {"type": "boolean", "description": "False when the list already looked like that"},
        "feeds": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["changed", "feeds"],
}

# feeds: the cached entries in settings order. fetched_at drives the schedule of
# THIS process (0 forces a fetch at start); updated_at is the persisted stamp the
# flyout shows. Handlers and the worker mutate under the lock, render() snapshots.
state: dict = {
    "feeds": [],
    "fetched_at": 0,
    "updated_at": 0,
    "busy": False,
    "pending": False,
    "draft": "",
    "form_error": "",
}
lock = threading.Lock()


# --- settings ------------------------------------------------------------


def number(key: str) -> int:
    """A numeric setting within its bounds; a bad value falls back with a warning."""
    default, low, high = NUMBERS[key]
    raw = app.settings.get(key, default)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        app.log("warn", f"{key} is not a number; using {default}", value=repr(raw)[:40])
        return default
    if not low <= value <= high:
        app.log("warn", f"{key} is outside {low}-{high}; clamped", value=value)
    return min(high, max(low, value))


def feed_urls() -> list[str]:
    """The configured feed URLs, trimmed and unique; unusable entries are skipped."""
    raw = app.settings.get("feeds", [])
    if not isinstance(raw, list):
        app.log("warn", "feeds is not a list; treating it as empty")
        return []
    urls: list[str] = []
    for entry in raw:
        url = feeds.normalize_url(entry)
        if not url:
            app.log("warn", "ignoring a feed entry that is not an http(s) URL", entry=repr(entry)[:80])
        elif url not in urls:
            urls.append(url)
    return urls


def save_urls(urls: list[str]) -> None:
    """set_settings REPLACES the whole object; settings_changed() then renders and fetches."""
    app.set_settings({**app.settings, "feeds": urls})


# --- cache ---------------------------------------------------------------


def load_cache() -> None:
    path = app.data_dir / CACHE_FILE
    try:
        cached = feeds.load_cache(path)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as error:
        app.log("warn", "ignoring an unreadable feed cache", error=str(error), hint=f"remove {path.name}")
        return
    with lock:
        state["feeds"] = cached["feeds"]
        state["updated_at"] = cached["fetchedAt"]


def save_cache() -> None:
    with lock:
        snapshot = {"feeds": state["feeds"], "fetchedAt": state["updated_at"]}
    try:
        feeds.save_cache(app.data_dir / CACHE_FILE, snapshot)
    except OSError as error:
        app.log("warn", "could not write the feed cache", error=str(error))


# --- rendering -----------------------------------------------------------


def render() -> None:
    """Push every surface from a snapshot of the state; safe from any thread."""
    with lock:
        snapshot = dict(state)
    now = int(time.time())
    items = feeds.merged(snapshot["feeds"])
    has_feeds = bool(snapshot["feeds"])
    failed = sum(1 for feed in snapshot["feeds"] if feed["error"])
    app.render(TILE, "tile", views.tile(items[: number("tileItems")], has_feeds, failed, app.t))
    app.render(TILE, "hover", views.hover(items, has_feeds, app.t))
    app.render(TILE, "flyout", views.flyout(snapshot, items, now, app.t))


# --- refreshing ----------------------------------------------------------


def apply_urls(urls: list[str]) -> bool:
    """Line the state up with the settings (URL set, maxPerFeed); True when the set of feeds changed."""
    limit = number("maxPerFeed")
    with lock:
        known = {feed["url"]: feed for feed in state["feeds"]}
        changed = list(known) != urls
        state["feeds"] = [
            {**feed, "items": feed["items"][:limit]} for feed in (known.get(url) or feeds.new_entry(url) for url in urls)
        ]
    return changed


def refresh() -> bool:
    """Start one fetch of every feed; a request during a fetch runs right after it."""
    with lock:
        if state["busy"]:
            state["pending"] = True
            return False
        state["busy"] = True
        entries = list(state["feeds"])
    render()
    threading.Thread(target=fetch_all, args=(entries, number("maxPerFeed")), daemon=True).start()
    return True


def fetch_all(entries: list[dict], max_items: int) -> None:
    """Worker thread: fetch, then merge into whatever the feed list is NOW."""
    now = int(time.time())
    results = {feed["url"]: feed for feed in feeds.refresh_all(entries, max_items, now)}
    with lock:
        state["feeds"] = [results.get(feed["url"], feed) for feed in state["feeds"]]
        state.update(fetched_at=now, updated_at=now, busy=False)
        again, state["pending"] = state["pending"], False
        failed = [(feed["url"], feed["error"]) for feed in state["feeds"] if feed["error"]]
    save_cache()
    for url, error in failed:
        app.log("warn", "feed update failed; showing its last items", url=url, error=error)
    render()
    if again:
        refresh()


# --- lifecycle -----------------------------------------------------------


@app.on_ready
def ready() -> None:
    """Cached headlines first; the first tick starts the fetch."""
    load_cache()
    apply_urls(feed_urls())
    render()


@app.every(TICK_SECONDS)
def tick() -> None:
    with lock:
        due = bool(state["feeds"]) and time.time() - state["fetched_at"] >= number("refreshMinutes") * 60
    if due:
        refresh()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    changed = apply_urls(feed_urls())
    render()
    if changed:
        refresh()


# --- actions -------------------------------------------------------------


def add(raw: str) -> None:
    url = feeds.normalize_url(raw)
    urls = feed_urls()
    problem = "news.invalidUrl" if not url else "news.duplicate" if url in urls else ""
    with lock:
        state["draft"] = raw.strip() if problem else ""
        state["form_error"] = app.t(problem) if problem else ""
    if problem:
        render()
        return
    save_urls([*urls, url])


@app.on_action(TILE)
def on_action(name: str, value: object) -> None:
    if name == "refresh":
        refresh()
    elif name == "add":
        add(str(value.get("url", "")) if isinstance(value, dict) else "")
    elif name == "remove":
        urls = feed_urls()
        if value in urls:
            save_urls([url for url in urls if url != value])


# --- agent commands ------------------------------------------------------


def item_out(item: dict) -> dict:
    return {
        "title": item["title"],
        "link": item["link"],
        "feed": item["feed"],
        "published": datetime.fromtimestamp(item["ts"], UTC).isoformat(),
        "summary": item["summary"],
    }


def url_argument(arguments: dict) -> str:
    url = feeds.normalize_url(arguments.get("url"))
    if not url:
        raise ValueError("url must be an absolute http:// or https:// address")
    return url


@app.command(
    "latest",
    description="The newest headlines across all feeds, newest first.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "How many items (default 10)"}
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "link": {"type": "string"},
                        "feed": {"type": "string", "description": "Title of the feed the item came from"},
                        "published": {"type": "string", "description": "ISO 8601, UTC"},
                        "summary": {"type": "string", "description": "Plain text, up to 160 characters, may be empty"},
                    },
                },
            }
        },
        "required": ["items"],
    },
)
def latest(arguments: dict) -> dict:
    limit = arguments.get("limit", LATEST_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    with lock:
        snapshot = list(state["feeds"])
    return {"items": [item_out(item) for item in feeds.merged(snapshot, limit)]}


@app.command(
    "refresh",
    description="Fetch every feed now, in the background. Call latest afterwards for the result.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {
            "started": {"type": "boolean", "description": "False when a fetch was already running; it runs again right after"},
            "feeds": {"type": "integer"},
        },
        "required": ["started", "feeds"],
    },
)
def refresh_command(arguments: dict) -> dict:
    with lock:
        count = len(state["feeds"])
    return {"started": refresh(), "feeds": count}


@app.command(
    "add",
    description="Add a feed URL to the settings; it is fetched right away.",
    input_schema=URL_SCHEMA,
    output_schema=FEEDS_SCHEMA,
)
def add_command(arguments: dict) -> dict:
    url = url_argument(arguments)
    urls = feed_urls()
    if url in urls:
        return {"changed": False, "feeds": urls}
    save_urls([*urls, url])
    return {"changed": True, "feeds": [*urls, url]}


@app.command(
    "remove",
    description="Remove a feed URL from the settings.",
    input_schema=URL_SCHEMA,
    output_schema=FEEDS_SCHEMA,
)
def remove_command(arguments: dict) -> dict:
    url = url_argument(arguments)
    urls = feed_urls()
    if url not in urls:
        return {"changed": False, "feeds": urls}
    kept = [entry for entry in urls if entry != url]
    save_urls(kept)
    return {"changed": True, "feeds": kept}


if __name__ == "__main__":
    app.run()
