# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Clipboard History: everything you copied as text, found again in one click.

The clipboard is polled every pollSeconds through clipboard.read_text() (one
platform tool per OS, no daemon). New text goes to the top of model.History,
which lives in app.data_dir/history.json and is written once per change.
Pause stops recording and survives restarts as the `paused` setting. Nothing
leaves the machine.
"""

import json
import time
from pathlib import Path

import clipboard
import views
from model import History
from smabar_sdk import Plugin

app = Plugin()

TILE = "clipboard"
HISTORY_FILE = "history.json"
TICK_SECONDS = 0.5  # the smallest pollSeconds; tick() waits until the configured interval is due
RENDER_SECONDS = 60  # relative times ("2 min ago") are refreshed this often
DEFAULTS = {"pollSeconds": 1.0, "maxChars": 20000.0, "maxEntries": 100.0}
MINIMUMS = {"pollSeconds": 0.5, "maxChars": 1.0, "maxEntries": 1.0}
# ponytail: one clipboard read per poll inside the handler is fine at 1 s (a few ms on
# every platform). The ceiling is a native watcher per platform (wl-paste --watch,
# GetClipboardSequenceNumber, NSPasteboard.changeCount) if CPU ever shows.

history = History(Path(HISTORY_FILE))  # re-pointed at app.data_dir in on_ready
state: dict = {"last_seen": None, "error": "", "poll_due": 0.0, "render_due": 0.0}


def number(key: str) -> float:
    """A numeric setting above its minimum; a bad value falls back with a warning."""
    try:
        value = float(app.settings.get(key, DEFAULTS[key]))
    except (TypeError, ValueError):
        app.log("warn", f"{key} is not a number; using {DEFAULTS[key]:g}")
        value = DEFAULTS[key]
    return max(MINIMUMS[key], value)


def paused() -> bool:
    return app.settings.get("paused") is True


def render() -> None:
    entries = history.ordered()
    now = int(time.time())
    latest = history.entries[0]["text"] if history.entries else None
    app.render(TILE, "tile", views.tile(latest, paused(), clipboard.MISSING_TOOL, app.t))
    app.render(TILE, "hover", views.hover(entries, paused(), now, app.t))
    app.render(
        TILE,
        "flyout",
        views.flyout(entries, history.unpinned(), paused(), state["error"], now, app.t),
    )
    state["render_due"] = time.monotonic() + RENDER_SECONDS


def commit(changed: bool) -> None:
    """Persists and redraws after a store mutation; an unchanged store costs nothing."""
    if changed:
        history.save()
        render()


def fail(message: str) -> None:
    """Shows a read error once; the last entries stay on screen."""
    if message != state["error"]:
        state["error"] = message
        app.log("warn", "clipboard read failed", error=message)
        render()


def baseline() -> None:
    """Remembers what the clipboard holds right now so it is never recorded.

    Runs at start and when recording resumes: a secret copied while paused (or
    before the plugin started) must not slip into the history.
    """
    try:
        state["last_seen"] = clipboard.read_text()
    except clipboard.ClipboardError as exc:
        fail(f"{app.t('clip.readError')}: {exc}")


def poll() -> None:
    """One clipboard read; new text goes to the top of the history."""
    try:
        text = clipboard.read_text()
    except clipboard.ClipboardError as exc:
        fail(f"{app.t('clip.readError')}: {exc}")
        return
    if state["error"]:
        state["error"] = ""
        render()
    if text == state["last_seen"]:
        return
    state["last_seen"] = text
    if text is not None:
        commit(
            history.add(
                text,
                int(time.time()),
                max_chars=int(number("maxChars")),
                max_entries=int(number("maxEntries")),
            )
        )


@app.on_ready
def ready() -> None:
    global history
    history = History(app.data_dir / HISTORY_FILE)
    try:
        history.load()
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        app.log("warn", "history.json could not be read; starting with an empty history", error=str(exc))
    if clipboard.MISSING_TOOL:
        state["error"] = views.tr(app.t, "clip.installHint", tool=clipboard.MISSING_TOOL)
        app.log("warn", "no clipboard reader found", install=clipboard.MISSING_TOOL)
    elif not paused():
        baseline()
    render()


@app.every(TICK_SECONDS)
def tick() -> None:
    now = time.monotonic()
    if now >= state["render_due"]:
        render()
    if clipboard.MISSING_TOOL or paused() or now < state["poll_due"]:
        return
    state["poll_due"] = now + number("pollSeconds")
    poll()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    if history.trim(int(number("maxEntries"))):
        history.save()
    if not clipboard.MISSING_TOOL and not paused():
        baseline()
    render()


@app.on_action(TILE, "pause")
def on_pause(action: str, value: object) -> None:
    # set_settings REPLACES the whole settings object; settings_changed() renders.
    app.set_settings({**app.settings, "paused": value is True or value == "true"})


@app.on_action(TILE, "pin")
def on_pin(action: str, value: object) -> None:
    args = json.loads(value) if isinstance(value, str) else value if isinstance(value, dict) else {}
    commit(history.pin(str(args.get("id")), args.get("pinned") is True))


@app.on_action(TILE, "delete")
def on_delete(action: str, value: object) -> None:
    commit(history.delete(str(value)))


@app.on_action(TILE, "clear")
def on_clear(action: str, value: object) -> None:
    commit(history.clear() > 0)


ID = {"type": "string", "minLength": 1, "maxLength": 64}
SUMMARY = {
    "type": "object",
    "properties": {
        "id": ID,
        "preview": {"type": "string", "description": "The text on one line, at most 120 characters"},
        "chars": {"type": "integer"},
        "lines": {"type": "integer"},
        "at": {"type": "integer", "description": "Unix seconds of the last copy"},
        "pinned": {"type": "boolean"},
    },
    "required": ["id", "preview", "chars", "lines", "at", "pinned"],
}
ENTRY_RESULT = {"type": "object", "properties": {"entry": SUMMARY}, "required": ["entry"]}


def summary(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "preview": views.one_line(entry["text"], 120),
        "chars": len(entry["text"]),
        "lines": entry["text"].count("\n") + 1,
        "at": int(entry["at"]),
        "pinned": entry["pinned"],
    }


def entry_id(args: dict) -> str:
    value = args.get("id")
    if not isinstance(value, str) or history.get(value) is None:
        raise ValueError("id must name an existing entry; use list to find one")
    return value


def flag(args: dict, key: str) -> bool:
    value = args.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


@app.command(
    "list",
    description="List clipboard entries, pinned first, then newest first. query filters case-insensitively.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {"entries": {"type": "array", "items": SUMMARY}, "total": {"type": "integer"}},
        "required": ["entries", "total"],
    },
)
def cmd_list(args: dict) -> dict:
    query = args.get("query", "")
    limit = args.get("limit", 20)
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    return {"entries": [summary(e) for e in history.search(query, limit)], "total": len(history.entries)}


@app.command(
    "get",
    description="Read one entry with its full text.",
    input_schema={"type": "object", "properties": {"id": ID}, "required": ["id"], "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {"entry": {**SUMMARY, "properties": {**SUMMARY["properties"], "text": {"type": "string"}}}},
        "required": ["entry"],
    },
)
def cmd_get(args: dict) -> dict:
    entry = history.get(entry_id(args))
    return {"entry": {**summary(entry), "text": entry["text"]}}


@app.command(
    "pin",
    description="Pin or unpin an entry. Pinned entries stay on top and never fall off the limit.",
    input_schema={
        "type": "object",
        "properties": {"id": ID, "pinned": {"type": "boolean"}},
        "required": ["id", "pinned"],
        "additionalProperties": False,
    },
    output_schema=ENTRY_RESULT,
)
def cmd_pin(args: dict) -> dict:
    target = entry_id(args)
    commit(history.pin(target, flag(args, "pinned")))
    return {"entry": summary(history.get(target))}


@app.command(
    "delete",
    description="Delete one entry.",
    input_schema={"type": "object", "properties": {"id": ID}, "required": ["id"], "additionalProperties": False},
    output_schema={"type": "object", "properties": {"deleted": ID}, "required": ["deleted"]},
)
def cmd_delete(args: dict) -> dict:
    target = entry_id(args)
    commit(history.delete(target))
    return {"deleted": target}


@app.command(
    "clear",
    description="Remove every unpinned entry; pinned entries stay.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={"type": "object", "properties": {"removed": {"type": "integer"}}, "required": ["removed"]},
)
def cmd_clear(args: dict) -> dict:
    removed = history.clear()
    commit(removed > 0)
    return {"removed": removed}


@app.command(
    "pause",
    description="Pause or resume recording. What sits in the clipboard at resume time is not recorded.",
    input_schema={
        "type": "object",
        "properties": {"paused": {"type": "boolean"}},
        "required": ["paused"],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"paused": {"type": "boolean"}}, "required": ["paused"]},
)
def cmd_pause(args: dict) -> dict:
    value = flag(args, "paused")
    app.set_settings({**app.settings, "paused": value})
    return {"paused": value}


if __name__ == "__main__":
    app.run()
