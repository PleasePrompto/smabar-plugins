# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Keep Awake: one switch that keeps the screen on and the computer from sleeping.

The platform inhibitors and the timer math live in backend.py, the markup in
views.py. Nothing is persisted on purpose: the plugin always starts off, so a
forgotten session never survives a restart.
"""

import atexit
import os
import platform
import shutil
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from smabar_sdk import Plugin

import views
from backend import (
    MAX_MINUTES,
    BackendError,
    choose_backend,
    end_at,
    ended,
    remaining_minutes,
)

app = Plugin()

TILE = "awake"
DEFAULT_MINUTES = 60
TICK_SECONDS = 10
POPUP_MS = 8000
STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "on": {"type": "boolean"},
        "remainingMinutes": {"type": ["integer", "null"]},
        "endsAt": {"type": ["string", "null"], "description": "Local ISO time, null when untimed or off"},
        "mechanism": {"type": "string", "description": "The inhibitor in use, empty when off"},
        "error": {"type": "string", "description": "Why the last start failed, empty otherwise"},
    },
    "required": ["on", "remainingMinutes", "endsAt", "mechanism", "error"],
}

# Everything the surfaces show. Handlers and the switch thread mutate it under
# the lock; render() reads a snapshot.
state: dict = {"on": False, "busy": False, "minutes": 0, "end_at": None, "mechanism": "", "error": ""}
lock = threading.Lock()
backend_lock = threading.Lock()  # one start/stop at a time
backend = choose_backend(
    platform.system(),
    shutil.which,
    os.environ.get("DISPLAY", ""),
    Path(__file__).with_name("inhibit_linux.py"),
    lambda message: app.log("info", message),
)


def default_minutes() -> int:
    """The defaultMinutes setting; a bad value falls back instead of crashing."""
    value = app.settings.get("defaultMinutes", DEFAULT_MINUTES)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_MINUTES:
        app.log("warn", "defaultMinutes must be 0 to 1440; using 60", value=value)
        return DEFAULT_MINUTES
    return int(value)


def render() -> None:
    with lock:
        snapshot = dict(state)
    left = remaining_minutes(snapshot["end_at"], time.time())
    app.render(TILE, "tile", views.tile(snapshot, app.t))
    app.render(TILE, "hover", views.hover(snapshot, left, app.t))
    app.render(TILE, "flyout", views.flyout(snapshot, app.t))


def switch(on: bool, minutes: int) -> None:
    """Start or stop the inhibitor and publish the result; one caller at a time."""
    with backend_lock:
        with lock:
            running, mechanism = state["on"], state["mechanism"]
        try:
            if on:
                if not running:
                    mechanism = backend.start()
                with lock:
                    state.update(
                        on=True,
                        minutes=minutes,
                        end_at=end_at(time.time(), minutes),
                        mechanism=mechanism,
                        error="",
                    )
                app.log("info", "keep awake on", mechanism=mechanism, minutes=minutes)
            else:
                backend.stop()
                with lock:
                    state.update(on=False, minutes=0, end_at=None, mechanism="", error="")
                app.log("info", "keep awake off")
        except BackendError as exc:
            backend.stop()
            with lock:
                state.update(on=False, minutes=0, end_at=None, mechanism="", error=str(exc))
            app.log("warn", "could not keep the computer awake", error=str(exc))
        finally:
            with lock:
                state["busy"] = False
    render()


def request(on: bool, minutes: int) -> bool:
    """UI path: show the busy tile at once, switch on a thread (subprocesses)."""
    with lock:
        if state["busy"]:
            return False
        state["busy"] = True
    render()
    threading.Thread(target=switch, args=(on, minutes), daemon=True).start()
    return True


def status() -> dict:
    with lock:
        snapshot = dict(state)
    end = snapshot["end_at"]
    return {
        "on": snapshot["on"],
        "remainingMinutes": remaining_minutes(end, time.time()),
        "endsAt": datetime.fromtimestamp(end).astimezone().isoformat(timespec="seconds") if end else None,
        "mechanism": snapshot["mechanism"],
        "error": snapshot["error"],
    }


def minutes_argument(args: dict) -> int:
    if "minutes" not in args:
        return default_minutes()
    value = args["minutes"]
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_MINUTES:
        raise ValueError("minutes must be an integer from 0 (until switched off) to 1440")
    return value


@app.on_ready
def ready() -> None:
    render()


@app.every(TICK_SECONDS)
def tick() -> None:
    with lock:
        on = state["on"]
        due = on and ended(state["end_at"], time.time())
    if due:
        if request(False, 0):
            app.popups.show(TILE, "ended", views.popup(app.t), ttl_ms=POPUP_MS)
    elif on:
        render()  # the hover line counts the minutes down


@app.on_action(TILE, "toggle")
def on_toggle(action: str, value: object) -> None:
    request(value == "on", default_minutes())


@app.on_action(TILE, "duration")
def on_duration(action: str, value: object) -> None:
    try:
        minutes = int(str(value))
    except ValueError:
        app.log("warn", "duration is not a number", value=value)
        return
    if not 0 <= minutes <= MAX_MINUTES:
        app.log("warn", "duration must be 0 to 1440 minutes", value=minutes)
        return
    request(True, minutes)


@app.command(
    "on",
    description=(
        "Keep the screen on and the computer awake. minutes: 1 to 1440, 0 = until switched off; "
        "omitted = the defaultMinutes setting. Calling it while on only changes the duration."
    ),
    input_schema={
        "type": "object",
        "properties": {"minutes": {"type": "integer", "minimum": 0, "maximum": MAX_MINUTES}},
        "additionalProperties": False,
    },
    output_schema=STATUS_SCHEMA,
)
def command_on(args: dict) -> dict:
    switch(True, minutes_argument(args))
    return status()


@app.command(
    "off",
    description="Release every inhibitor; the screen and the computer follow the power settings again.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema=STATUS_SCHEMA,
)
def command_off(args: dict) -> dict:
    switch(False, 0)
    return status()


@app.command(
    "status",
    description="Whether Keep Awake is on, the minutes left and the inhibitor in use.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema=STATUS_SCHEMA,
)
def command_status(args: dict) -> dict:
    return status()


def release() -> None:
    """Never leave an inhibitor behind on a graceful stop."""
    backend.stop()


if __name__ == "__main__":
    atexit.register(release)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    app.run()
