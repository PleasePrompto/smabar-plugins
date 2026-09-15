# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Quick Notes: a scratchpad on the bar.

Jot something down in two seconds, find it again later. Every note is one
Markdown file in app.data_dir/notes, so any editor or Obsidian can open the
folder; the index is rebuilt from that folder on every rescan. Markup lives
in views.py, storage in model.py; this file is the glue.
"""

import time
from datetime import datetime

from smabar_sdk import Plugin

import views
from model import MAX_TEXT, Note, NoteError, NoteStore

app = Plugin()
TILE = "notes"
TILE_MODES = ("pinned", "latest", "count")
RESCAN_SECONDS = 30
TOAST_MS = 2500
UNDO_MS = 10_000
QUERY_CHARS = 200
LIST_LIMIT = 500

store: NoteStore | None = None
# One counter per draft field: a saved draft gets a new field name, so the
# shell does not restore the old text into the emptied textarea.
epochs = {"draft": 0, "compose": 0}
error = ""
last_deleted: Note | None = None


def db() -> NoteStore:
    if store is None:
        raise NoteError("storage", "note storage is not ready yet")
    return store


def tile_mode() -> str:
    value = app.settings.get("tileMode", TILE_MODES[0])
    if value in TILE_MODES:
        return value
    app.log("warn", "tileMode is not pinned, latest or count; using pinned", value=str(value))
    return TILE_MODES[0]


def render() -> None:
    notes = db().notes()
    app.render(TILE, "tile", views.tile(notes, tile_mode(), app.t))
    app.render(TILE, "hover", views.hover(notes[0] if notes else None, app.t))
    app.render(TILE, "flyout", views.flyout(notes, epochs, time.time(), error, app.t))


def add_note(text: str) -> Note:
    note = db().add(text)
    app.popups.show(TILE, "saved", views.toast_saved(note, app.t), ttl_ms=TOAST_MS)
    return note


def delete_note(note_id: str) -> Note:
    """Removes the note and keeps a copy for Undo until the next delete or undo."""
    global last_deleted
    last_deleted = db().delete(note_id)
    app.popups.show(TILE, "deleted", views.toast_deleted(last_deleted, app.t), ttl_ms=UNDO_MS)
    return last_deleted


def field(value: object, name: str) -> str:
    """One data-field value out of the dict a form submit or button click delivers."""
    return str(value.get(name, "")) if isinstance(value, dict) else ""


@app.on_ready
def ready() -> None:
    global store
    store = NoteStore(app.data_dir)
    store.load()
    render()


@app.every(RESCAN_SECONDS)
def tick() -> None:
    """Picks up files another editor changed; renders only when the folder changed."""
    if store is not None and store.rescan():
        render()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    render()


@app.on_action(TILE)
def on_action(name: str, value: object) -> None:
    global error, last_deleted
    if name == "tile":
        return  # the shell reports a plain click on the tile; nothing to do
    kind, _, note_id = name.partition(":")
    error = ""
    try:
        if kind in ("add", "compose"):
            slot = "draft" if kind == "add" else "compose"
            add_note(field(value, f"{slot}-{epochs[slot]}"))
            epochs[slot] += 1
        elif kind == "save":
            note = db().update(note_id, field(value, f"edit-{views.token(note_id)}"))
            app.popups.show(TILE, "saved", views.toast_saved(note, app.t), ttl_ms=TOAST_MS)
        elif kind == "pin":
            db().pin(None if db().get(note_id).pinned else note_id)
        elif kind == "delete":
            delete_note(note_id)
        elif kind == "undo":
            if last_deleted is None:
                raise NoteError("missing", "nothing to restore")
            db().restore(last_deleted)
            last_deleted = None
            app.popups.dismiss(TILE, "deleted")
        else:
            app.log("warn", "unknown action", action=name)
    except NoteError as exc:
        error = app.t(f"notes.error.{exc.key}")
        app.log("info", "note action rejected", action=name, reason=str(exc))
    except OSError as exc:
        error = app.t("notes.error.storage")
        app.log("error", "note storage failed", action=name, error=str(exc))
    render()


# --- agent commands -----------------------------------------------------------


def text_arg(args: dict, key: str, *, required: bool = True, maximum: int = MAX_TEXT) -> str:
    value = args.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        kind = "a non-empty" if required else "a"
        raise ValueError(f"{key} must be {kind} string of at most {maximum} characters")
    return value


def limit_arg(args: dict) -> int:
    value = args.get("limit", 50)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= LIST_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {LIST_LIMIT}")
    return value


def summary(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "preview": note.preview,
        "updated": datetime.fromtimestamp(note.updated).astimezone().isoformat(timespec="seconds"),
        "pinned": note.pinned,
    }


def listing(query: str, limit: int) -> dict:
    return {"notes": [summary(note) for note in db().notes(query)[:limit]]}


def schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


ID = {"type": "string", "minLength": 1, "description": "A note id from notes.list"}
QUERY = {"type": "string", "maxLength": QUERY_CHARS, "description": "Case-insensitive substring of the note text"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": LIST_LIMIT, "default": 50}
SUMMARY = schema(
    {
        "id": ID,
        "title": {"type": "string", "description": "First non-empty line without Markdown markers"},
        "preview": {"type": "string"},
        "updated": {"type": "string", "description": "ISO 8601 with the local UTC offset"},
        "pinned": {"type": "boolean"},
    },
    ["id", "title", "preview", "updated", "pinned"],
)
LISTING = schema({"notes": {"type": "array", "items": SUMMARY}}, ["notes"])


@app.command(
    "notes.add",
    description="Create a note from Markdown text; the first line becomes its title.",
    input_schema=schema({"text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}}, ["text"]),
    output_schema=schema({"id": ID, "title": {"type": "string"}}, ["id", "title"]),
)
def cmd_add(args: dict) -> dict:
    note = add_note(text_arg(args, "text"))
    render()
    return {"id": note.id, "title": note.title}


@app.command(
    "notes.list",
    description="List notes, pinned first and then newest first, optionally filtered by a query.",
    input_schema=schema({"query": QUERY, "limit": LIMIT}, []),
    output_schema=LISTING,
)
def cmd_list(args: dict) -> dict:
    return listing(text_arg(args, "query", required=False, maximum=QUERY_CHARS), limit_arg(args))


@app.command(
    "notes.search",
    description="Find notes whose text contains the query (case-insensitive).",
    input_schema=schema({"query": {**QUERY, "minLength": 1}, "limit": LIMIT}, ["query"]),
    output_schema=LISTING,
)
def cmd_search(args: dict) -> dict:
    return listing(text_arg(args, "query", maximum=QUERY_CHARS), limit_arg(args))


@app.command(
    "notes.get",
    description="Read one note including its full Markdown text.",
    input_schema=schema({"id": ID}, ["id"]),
    output_schema=schema({**SUMMARY["properties"], "text": {"type": "string"}}, [*SUMMARY["required"], "text"]),
)
def cmd_get(args: dict) -> dict:
    note = db().get(text_arg(args, "id", maximum=255))
    return {**summary(note), "text": note.text}


@app.command(
    "notes.delete",
    description="Delete a note; the user sees a toast with Undo for ten seconds.",
    input_schema=schema({"id": ID}, ["id"]),
    output_schema=schema({"deletedId": ID}, ["deletedId"]),
)
def cmd_delete(args: dict) -> dict:
    note = delete_note(text_arg(args, "id", maximum=255))
    render()
    return {"deletedId": note.id}


if __name__ == "__main__":
    # Guarded so the self-check can import this module without starting the RPC loop.
    app.run()
