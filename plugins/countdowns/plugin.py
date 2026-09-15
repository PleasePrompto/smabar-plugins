# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Countdowns: days until the things you look forward to (or dread).

Events live in app.data_dir/events.json (atomic writes). The day math is in
model.py, the markup in views.py; this file is the glue: state, settings,
surfaces, actions, agent commands and the once-a-day popup.
"""

import json
import os
import secrets
from datetime import date, datetime

import model
import views
from smabar_sdk import Plugin

app = Plugin()

TILE = "next"
EVENTS_FILE = "events.json"
HOVER_ROWS = 3
ERROR_KEYS = {
    "title": "countdowns.titleRequired",
    "date": "countdowns.errorDate",
    "past": "countdowns.errorPast",
    "time": "countdowns.errorTime",
    "id": "countdowns.errorMissing",
}
DATE_SCHEMA = {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "YYYY-MM-DD"}
EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "date": DATE_SCHEMA,
        "time": {"type": "string", "description": "HH:MM local time, or empty for an all-day event"},
        "repeatYearly": {"type": "boolean"},
        "when": {**DATE_SCHEMA, "description": "The day counted down to: the next anniversary for yearly events"},
        "days": {"type": "integer", "description": "Calendar days left; 0 today, negative once passed"},
        "status": {"enum": ["upcoming", "today", "past"]},
    },
}
EVENT_OUTPUT = {"type": "object", "properties": {"event": EVENT_SCHEMA}, "required": ["event"]}

events: list[dict] = []
error = ""  # the last rejected form action, shown until the next successful one
form_epoch = 0  # fresh field names after each add, so the form empties itself
published: dict[str, str] = {}  # last HTML per surface: ticks push only real changes
settings = {"keepPastDays": 3, "maxItems": 8, "notify": True}
last_day = ""


def today() -> date:
    return datetime.now().date()


def setting_int(key: str, default: int, low: int, high: int) -> int:
    value = app.settings.get(key, default)
    number = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if number is None or not low <= number <= high:
        app.log("warn", f"{key} must be a whole number from {low} to {high}; using {default}", value=value)
        return default
    return number


def apply_settings() -> None:
    settings["keepPastDays"] = setting_int("keepPastDays", 3, 0, 365)
    settings["maxItems"] = setting_int("maxItems", 8, 1, 50)
    notify = app.settings.get("notify", True)
    if not isinstance(notify, bool):
        app.log("warn", "notify must be true or false; using true", value=notify)
        notify = True
    settings["notify"] = notify


def load() -> None:
    """events.json into memory; a broken entry is skipped and logged, never fatal."""
    global events
    path = app.data_dir / EVENTS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        app.log("error", "events.json is unreadable; starting empty", error=str(exc))
        return
    loaded = []
    for item in raw if isinstance(raw, list) else []:
        try:
            event = model.make_event(
                str(item["id"]), item.get("title"), item.get("date"), item.get("time"), item.get("repeatYearly", False)
            )
        except (TypeError, KeyError, model.InvalidEvent) as exc:
            app.log("warn", "skipping a broken entry in events.json", error=str(exc))
            continue
        event["notifiedFor"] = str(item.get("notifiedFor", ""))
        loaded.append(event)
    events = loaded


def save() -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    path = app.data_dir / EVENTS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def find(event_id: str) -> dict:
    for event in events:
        if event["id"] == event_id:
            return event
    raise model.InvalidEvent("id", f"no countdown with id {event_id}")


def accept(event: dict) -> dict:
    """A one-time countdown older than keepPastDays would vanish on the next tick, so refuse it up front."""
    days = (date.fromisoformat(event["date"]) - today()).days
    if not event["repeatYearly"] and days < -settings["keepPastDays"]:
        raise model.InvalidEvent("past", f"date is more than {settings['keepPastDays']} days in the past")
    return event


def schedule() -> list[dict]:
    return model.describe(events, today(), settings["keepPastDays"])


def entry_for(event_id: str) -> dict:
    return model.describe([find(event_id)], today(), settings["keepPastDays"])[0]


def push(target: str, html: str) -> None:
    if published.get(target) != html:
        published[target] = html
        app.render(TILE, target, html)


def render() -> None:
    entries = schedule()
    upcoming = [entry for entry in entries if entry["days"] >= 0]
    nxt = upcoming[0] if upcoming else None
    live = model.live_countdown(nxt, datetime.now()) if nxt else ""
    push("tile", views.tile(nxt, live, app.t))
    push("hover", views.hover(upcoming[:HOVER_ROWS], app.t))
    push("flyout", views.flyout(entries, settings["maxItems"], f"new{form_epoch}", error, app.t))


def check_popups() -> None:
    """One popup per event and day, remembered in notifiedFor so a restart does not repeat it."""
    if not settings["notify"] or "popups" not in app.capabilities:
        return
    day = today().isoformat()
    changed = False
    for entry in schedule():
        if entry["days"] != 0 or entry["notifiedFor"] == day:
            continue
        result = app.popups.show(TILE, f"today-{entry['id']}", views.popup(entry, app.t))
        if result.get("state") == "suppressed":
            continue  # do-not-disturb: try again on the next tick
        find(entry["id"])["notifiedFor"] = day
        changed = True
    if changed:
        save()


def prune() -> None:
    global events
    kept = model.prune(events, today(), settings["keepPastDays"])
    if len(kept) != len(events):
        events = kept
        save()


def refresh() -> None:
    render()
    check_popups()


@app.on_ready
def ready() -> None:
    global last_day
    apply_settings()
    load()
    last_day = today().isoformat()
    prune()
    refresh()


@app.every(60)
def tick() -> None:
    global last_day
    day = today().isoformat()
    if day != last_day:
        last_day = day
        prune()
    refresh()


@app.on_settings_changed
def settings_changed(_settings: dict) -> None:
    apply_settings()
    prune()
    refresh()


def read_form(fields: dict, key: str) -> tuple[object, object, object, bool]:
    return (
        fields.get(f"title-{key}"),
        fields.get(f"date-{key}"),
        fields.get(f"time-{key}"),
        fields.get(f"yearly-{key}") == "true",
    )


@app.on_action(TILE)
def on_action(name: str, value: object) -> None:
    global error, form_epoch
    if name == "dismiss":
        app.popups.dismiss(TILE, f"today-{value}")
        return
    fields = value if isinstance(value, dict) else {}
    try:
        if name == "add":
            events.append(accept(model.make_event(secrets.token_hex(4), *read_form(fields, f"new{form_epoch}"))))
            form_epoch += 1
        elif name.startswith("save:"):
            event = find(name[5:])
            fresh = accept(model.make_event(event["id"], *read_form(fields, event["id"])))
            event.update({key: fresh[key] for key in ("title", "date", "time", "repeatYearly")})
        elif name == "remove":
            events.remove(find(str(value)))
        else:
            # The shell reports its own tile click as an action named "tile".
            app.log("debug", "ignoring an action without a handler", action=name)
            return
        error = ""
        save()
    except model.InvalidEvent as exc:
        error = app.t(ERROR_KEYS[exc.field])
        app.log("info", "countdown form rejected", action=name, field=exc.field, error=str(exc))
    refresh()


@app.command(
    "add",
    description="Add a countdown. The date is a calendar day (YYYY-MM-DD), the optional time is local HH:MM; "
    "repeatYearly rolls the event forward every year (birthdays, holidays).",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": model.TITLE_MAX},
            "date": DATE_SCHEMA,
            "time": {"type": "string", "description": "HH:MM local time; omit for an all-day event"},
            "repeatYearly": {"type": "boolean", "default": False},
        },
        "required": ["title", "date"],
        "additionalProperties": False,
    },
    output_schema=EVENT_OUTPUT,
)
def cmd_add(args: dict) -> dict:
    event = accept(
        model.make_event(
            secrets.token_hex(4), args.get("title"), args.get("date"), args.get("time"), args.get("repeatYearly", False)
        )
    )
    events.append(event)
    save()
    refresh()
    return {"event": entry_for(event["id"])}


@app.command(
    "list",
    description="Every visible countdown with its days left, soonest first; passed one-time events stay for keepPastDays.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {"events": {"type": "array", "items": EVENT_SCHEMA}},
        "required": ["events"],
    },
)
def cmd_list(_args: dict) -> dict:
    return {"events": schedule()}


@app.command(
    "remove",
    description="Delete a countdown by id (from list).",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string", "minLength": 1}},
        "required": ["id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"removedId": {"type": "string"}}, "required": ["removedId"]},
)
def cmd_remove(args: dict) -> dict:
    event = find(str(args.get("id", "")))
    events.remove(event)
    save()
    refresh()
    return {"removedId": event["id"]}


if __name__ == "__main__":
    app.run()
