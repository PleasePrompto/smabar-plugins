# /// script
# requires-python = ">=3.12"
# dependencies = ["icalendar==7.3.0", "recurring-ical-events==3.8.2"]
# ///
"""Next Meeting: the next appointment on the bar, from any calendar with an ICS address.

Every configured calendar (https URL, webcal:// URL or local .ics file) is
fetched in its own thread, expanded into occurrences for the next days
(agenda.py) and cached in app.data_dir as JSON: the bar shows the cached
agenda at once, the refresh runs in the background, and a calendar that fails
keeps its last good events plus a warning line. The tile counts down to the
next event (ticked by the shell), the flyout lists Now / Today / Tomorrow /
Later with Join buttons, a popup reminds shortly before each occurrence — once,
tracked in notified.json — and agents get next / list / refresh commands.
"""

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from smabar_sdk import Plugin

import agenda
import views

app = Plugin()

TILE = "meeting"
TICK_SECONDS = 60
TIMEOUT_SECONDS = 15
MAX_BYTES = 8 * 1024 * 1024
USER_AGENT = "smabar-next-meeting/1.0"
CACHE_FILE = "events.json"
NOTIFIED_FILE = "notified.json"
EVENT_KEYS = ("uid", "title", "start", "end", "allDay", "location", "joinUrl", "calendarIndex")
DEFAULTS = {"refreshMinutes": 10, "remindMinutes": 5, "lookaheadDays": 7}
LIMITS = {"refreshMinutes": (1, 1440), "remindMinutes": (0, 1440), "lookaheadDays": (1, 60)}

# feeds: per calendar (keyed by a hash of its address, so the secret URL stays
# in the settings) the last good events, when they were fetched, the current
# error and whether that error was announced. Mutated under the lock.
state: dict = {"feeds": {}, "updated": "", "busy": False, "lastFetch": 0.0}
lock = threading.Lock()
notified: dict[str, str] = {}  # occurrence key -> start; a reminder fires once
reminders: dict[str, str] = {}  # popup id -> end of the announced event
pushed: dict[str, str] = {}  # target -> last HTML, so an unchanged surface is not re-sent


# --- settings ------------------------------------------------------------


def sources() -> list[str]:
    raw = app.settings.get("calendars", [])
    if not isinstance(raw, list):
        app.log("warn", "calendars is not a list; treating it as empty")
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def number(key: str) -> int:
    low, high = LIMITS[key]
    try:
        value = int(float(app.settings.get(key, DEFAULTS[key])))
    except (TypeError, ValueError):
        app.log("warn", f"{key} is not a number; using {DEFAULTS[key]}")
        return DEFAULTS[key]
    return min(high, max(low, value))


def show_all_day() -> bool:
    value = app.settings.get("showAllDay", True)
    return value if isinstance(value, bool) else True


def feed_key(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def now_local() -> datetime:
    return datetime.now().astimezone()


# --- files ---------------------------------------------------------------


def write_json(name: str, payload: object) -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    path = app.data_dir / name
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        app.log("warn", f"could not write {name}", error=str(error))


def read_json(name: str) -> dict:
    try:
        payload = json.loads((app.data_dir / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        app.log("warn", f"ignoring an unreadable {name}", error=str(error))
        return {}
    return payload if isinstance(payload, dict) else {}


def load_cache() -> None:
    cached = read_json(CACHE_FILE)
    feeds = cached.get("feeds")
    with lock:
        if isinstance(feeds, dict):
            state["feeds"] = feeds
        state["updated"] = str(cached.get("updated", ""))


def save_cache() -> None:
    with lock:
        snapshot = {"feeds": state["feeds"], "updated": state["updated"]}
    write_json(CACHE_FILE, snapshot)


def load_notified() -> None:
    notified.update({key: value for key, value in read_json(NOTIFIED_FILE).items() if isinstance(value, str)})


def save_notified(now: datetime) -> None:
    """Keep only keys of occurrences from the last day; older ones cannot fire again."""
    horizon = now - timedelta(days=1)
    stale = [key for key, start in notified.items() if agenda.at(start, False) < horizon]
    for key in stale:
        del notified[key]
    write_json(NOTIFIED_FILE, notified)


# --- fetching ------------------------------------------------------------


def read_source(source: str) -> bytes:
    """ICS bytes from an http(s)/webcal URL or a local file, capped at MAX_BYTES."""
    if source.startswith(("http://", "https://", "webcal://")):
        url = "https://" + source.removeprefix("webcal://") if source.startswith("webcal://") else source
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(MAX_BYTES + 1)
    else:
        data = Path(os.path.expanduser(source)).read_bytes()
    if len(data) > MAX_BYTES:
        raise OverflowError("calendar larger than the 8 MB limit")
    return data


def load_source(source: str, start: datetime, end: datetime) -> tuple[list[dict], dict | None]:
    """(events, None) on success, ([], error) otherwise; error is {kind, detail} for the locale."""
    try:
        return agenda.parse_ics(read_source(source), start, end), None
    except urllib.error.HTTPError as error:
        return [], {"kind": "http", "detail": str(error.code)}
    except urllib.error.URLError as error:
        kind = "timeout" if isinstance(error.reason, TimeoutError) else "network"
        return [], {"kind": kind, "detail": str(error.reason)[:80]}
    except FileNotFoundError:
        return [], {"kind": "missing", "detail": ""}
    except TimeoutError:
        return [], {"kind": "timeout", "detail": ""}
    except OverflowError:
        return [], {"kind": "large", "detail": ""}
    except OSError as error:
        return [], {"kind": "network", "detail": str(error)[:80]}
    except Exception as error:  # noqa: BLE001 - untrusted feed: one broken calendar must not take the others down
        app.log("warn", "calendar could not be parsed", error=f"{type(error).__name__}: {error}"[:200])
        return [], {"kind": "parse", "detail": type(error).__name__}


def fetch_all() -> None:
    """Every calendar in its own thread; a failing one keeps its last good events."""
    configured = sources()
    now = now_local()
    start, end = now - timedelta(hours=1), now + timedelta(days=number("lookaheadDays"))
    results: dict[str, tuple[list[dict], dict | None]] = {}
    if configured:
        with ThreadPoolExecutor(max_workers=len(configured)) as pool:
            futures = {source: pool.submit(load_source, source, start, end) for source in configured}
            results = {source: future.result() for source, future in futures.items()}
    stamp = now.strftime("%H:%M")
    failures: list[tuple[int, dict]] = []
    with lock:
        feeds = {}
        for index, source in enumerate(configured, start=1):
            key = feed_key(source)
            feed = state["feeds"].get(key, {"events": [], "okAt": "", "error": None, "failNotified": False})
            events, error = results[source]
            if error is None:
                feed.update(events=events, okAt=stamp, error=None, failNotified=False)
            else:
                feed["error"] = error
                if feed["okAt"] and not feed["failNotified"]:
                    feed["failNotified"] = True
                    failures.append((index, error))
            feeds[key] = feed
        state.update(feeds=feeds, updated=stamp, busy=False)
    save_cache()
    for index, error in failures:
        app.log("warn", "calendar stopped refreshing", calendar=index, **error)
        if "popups" in app.capabilities:
            app.popups.show(TILE, f"fail-{index}", views.failure(index, error_text(error), app.t), ttl_ms=15000)
    app.log("info", "agenda refreshed", calendars=len(configured), failed=len([r for r in results.values() if r[1]]))
    render_all()


def refresh() -> None:
    """Start one background fetch; a request while one runs is folded into it."""
    with lock:
        if state["busy"]:
            return
        state.update(busy=True, lastFetch=time.monotonic())
    render_all()
    threading.Thread(target=fetch_all, daemon=True).start()


# --- rendering -----------------------------------------------------------


def error_text(error: dict) -> str:
    return app.t(f"meeting.err.{error['kind']}").replace("{detail}", str(error["detail"]))


def current() -> tuple[dict[str, list[dict]], list[tuple[int, str]], dict]:
    """The agenda groups, the warning lines and a snapshot of the state, from the configured calendars."""
    configured = sources()
    with lock:
        feeds = {key: dict(feed) for key, feed in state["feeds"].items()}
        snapshot = {
            "updated": state["updated"],
            "busy": state["busy"],
            "calendars": len(configured),
            "now": now_local(),
        }
    events, warnings = [], []
    for index, source in enumerate(configured):
        feed = feeds.get(feed_key(source))
        if feed is None:
            continue
        events.extend({**event, "calendarIndex": index} for event in feed["events"])
        if feed["error"]:
            warnings.append((index + 1, error_text(feed["error"])))
    groups = agenda.sections(agenda.upcoming(events, snapshot["now"], show_all_day()), snapshot["now"])
    return groups, warnings, snapshot


def push(target: str, html: str) -> None:
    if pushed.get(target) != html:
        pushed[target] = html
        app.render(TILE, target, html)


def render_all() -> tuple[dict[str, list[dict]], datetime]:
    """Push every surface from the current state; thread-safe, returns the groups for the reminder check."""
    groups, warnings, snapshot = current()
    configured = snapshot["calendars"] > 0
    head, group = agenda.headline(groups)
    push("tile", views.tile(head, group, snapshot["now"], configured, app.t))
    push("hover", views.hover(groups, configured, app.t))
    push(
        "flyout",
        views.flyout(
            groups,
            warnings,
            updated=snapshot["updated"],
            busy=snapshot["busy"],
            calendars=snapshot["calendars"],
            days=number("lookaheadDays"),
            t=app.t,
        ),
    )
    return groups, snapshot["now"]


# --- reminders -----------------------------------------------------------


def remind(groups: dict[str, list[dict]], now: datetime) -> None:
    """One popup per occurrence, remindMinutes before it starts; dismissed when the event ends."""
    minutes = number("remindMinutes")
    if not minutes or "popups" not in app.capabilities:
        return
    for event in groups["today"] + groups["tomorrow"]:
        if event["allDay"]:
            continue
        key = f"{event['uid']}|{event['start']}"
        lead = agenda.at(event["start"], False) - now
        if key in notified or not timedelta(minutes=-1) < lead <= timedelta(minutes=minutes):
            continue
        notified[key] = event["start"]
        save_notified(now)
        popup_id = "rem-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        reminders[popup_id] = event["end"]
        app.popups.show(TILE, popup_id, views.reminder(event, popup_id, app.t))
        app.log("info", "reminder shown", title=event["title"], start=event["start"])
    for popup_id, end in list(reminders.items()):
        if agenda.at(end, False) <= now:
            app.popups.dismiss(TILE, popup_id)
            del reminders[popup_id]


# --- lifecycle and actions -----------------------------------------------


@app.on_ready
def ready() -> None:
    """Cached agenda first; the first tick fetches right away."""
    load_cache()
    load_notified()
    render_all()


def schedule_transition(groups: dict[str, list[dict]], now: datetime) -> None:
    """Re-render exactly when the headline event starts or ends within this tick,
    so the tile flips from the countdown to "until …" instead of resting on "in 00 min"."""
    head, group = agenda.headline(groups)
    if head is None or head["allDay"]:
        return
    moment = agenda.at(head["end" if group == "now" else "start"], False)
    wait = (moment - now).total_seconds()
    if 0 < wait <= TICK_SECONDS:
        threading.Timer(wait + 1, render_all).start()


@app.every(TICK_SECONDS)
def tick() -> None:
    if time.monotonic() - state["lastFetch"] >= number("refreshMinutes") * 60:
        refresh()
    groups, now = render_all()
    remind(groups, now)
    schedule_transition(groups, now)


@app.on_action(TILE, "refresh")
def on_refresh(action: str, value: object) -> None:
    with lock:
        state["lastFetch"] = 0.0
    refresh()


@app.on_action(TILE, "dismiss")
def on_dismiss(action: str, value: object) -> None:
    popup_id = str(value)
    reminders.pop(popup_id, None)
    app.popups.dismiss(TILE, popup_id)


@app.popups.on_event
def popup_event(event: dict) -> None:
    """Delivery outcomes, so a reminder that never showed up can be traced in the log."""
    popup_id, state = str(event.get("popupId")), str(event.get("state"))
    if state in ("dismissed", "expired", "dropped"):
        reminders.pop(popup_id, None)
    app.log("info", f"popup {state}", popup=popup_id, reason=str(event.get("reason") or ""))


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    wanted = {feed_key(source) for source in sources()}
    with lock:
        state["feeds"] = {key: feed for key, feed in state["feeds"].items() if key in wanted}
        state["lastFetch"] = 0.0  # a running fetch used the old calendars: the next tick fetches again
    refresh()


# --- agent commands ------------------------------------------------------

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "uid": {"type": "string"},
        "title": {"type": "string"},
        "start": {"type": "string", "description": "ISO 8601 in local time; a plain date for all-day events"},
        "end": {"type": "string", "description": "Exclusive end, same format as start"},
        "allDay": {"type": "boolean"},
        "location": {"type": "string"},
        "joinUrl": {"type": "string", "description": "Video-meeting link, empty when none was found"},
        "calendarIndex": {"type": "integer", "description": "Position in the calendars setting, from 0"},
    },
    "required": list(EVENT_KEYS),
}
WARNINGS_SCHEMA = {"type": "array", "items": {"type": "string"}, "description": "One line per calendar that failed"}


def output(event: dict) -> dict:
    return {key: event[key] for key in EVENT_KEYS}


@app.command(
    "meeting.next",
    description="The event the tile shows: running now, else the next one today (all-day only when nothing timed is left).",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {
            "event": {"anyOf": [EVENT_SCHEMA, {"type": "null"}]},
            "status": {"enum": ["now", "today", "none"]},
            "warnings": WARNINGS_SCHEMA,
        },
        "required": ["event", "status", "warnings"],
    },
)
def command_next(arguments: dict) -> dict:
    groups, warnings, _snapshot = current()
    head, group = agenda.headline(groups)
    return {
        "event": output(head) if head else None,
        "status": group or "none",
        "warnings": [f"{index}: {error}" for index, error in warnings],
    }


@app.command(
    "meeting.list",
    description="Upcoming events from the cached agenda, sorted by start; days limits how far ahead (default: the lookaheadDays setting).",
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 60}},
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": EVENT_SCHEMA},
            "updated": {
                "type": "string",
                "description": "Local time of the last fetch, HH:MM, empty before the first one",
            },
            "warnings": WARNINGS_SCHEMA,
        },
        "required": ["events", "updated", "warnings"],
    },
)
def command_list(arguments: dict) -> dict:
    days = arguments.get("days", number("lookaheadDays"))
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 60:
        raise ValueError("days must be an integer from 1 to 60")
    groups, warnings, snapshot = current()
    horizon = snapshot["now"] + timedelta(days=days)
    events = [
        output(event)
        for group in ("now", "today", "tomorrow", "later")
        for event in groups[group]
        if agenda.at(event["start"], event["allDay"]) < horizon
    ]
    return {"events": events, "updated": snapshot["updated"], "warnings": [f"{i}: {e}" for i, e in warnings]}


@app.command(
    "meeting.refresh",
    description="Fetch every calendar now and wait for the result.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {
            "calendars": {"type": "integer"},
            "events": {"type": "integer", "description": "Upcoming events after the fetch"},
            "updated": {"type": "string"},
            "warnings": WARNINGS_SCHEMA,
        },
        "required": ["calendars", "events", "updated", "warnings"],
    },
)
def command_refresh(arguments: dict) -> dict:
    with lock:
        state.update(busy=True, lastFetch=time.monotonic())
    fetch_all()
    groups, warnings, snapshot = current()
    return {
        "calendars": snapshot["calendars"],
        "events": sum(len(group) for group in groups.values()),
        "updated": snapshot["updated"],
        "warnings": [f"{index}: {error}" for index, error in warnings],
    }


if __name__ == "__main__":
    app.run()
