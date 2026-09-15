# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Focus Timer: a Pomodoro timer on the bar.

Focus blocks, short breaks and a long break after every fourth block. The
state machine lives in model.py (testable without the bar), the markup in
views.py; this file is the glue: settings, persistence, the one-second tick,
actions, agent commands, the done popup and the chime.

The tile and flyout carry data-sb-countdown, so the shell ticks the digits and
this process renders only when the state changes. The tick only checks whether
a running phase has ended. Nothing runs on its own after a phase ends: the
next phase waits pending until Start.
"""

import array
import json
import math
import os
import wave
from datetime import datetime, timezone

import model
import views
from smabar_sdk import Plugin, RpcError

app = Plugin()

TILE = "timer"
STATE_FILE = "state.json"
CHIME_FILE = "chime.wav"
POPUP = "phase-done"
POPUP_TTL_MS = 120_000  # the pending phase stays visible on the tile, so the toast may expire
MAX_LABEL = 80
MAX_MINUTES = 180
# setting name -> (model key, minimum, maximum, default)
SETTINGS = {
    "focusMinutes": ("focus", 1, MAX_MINUTES, 25),
    "shortBreakMinutes": ("shortBreak", 1, 60, 5),
    "longBreakMinutes": ("longBreak", 1, 120, 15),
    "longBreakEvery": ("longBreakEvery", 1, 12, 4),
}
STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "phase": {"enum": [model.IDLE, *model.PHASES]},
        "running": {"type": "boolean"},
        "remainingSeconds": {"type": "integer", "minimum": 0},
        "endsAt": {"type": ["string", "null"], "description": "ISO timestamp (UTC) while running"},
        "label": {"type": "string"},
        "completedToday": {"type": "integer", "minimum": 0},
        "focusMinutesToday": {"type": "integer", "minimum": 0},
    },
    "required": ["phase", "running", "remainingSeconds", "endsAt", "label", "completedToday", "focusMinutesToday"],
}
NO_INPUT = {"type": "object", "properties": {}, "additionalProperties": False}

state = model.new_state()
config = dict(model.DEFAULT_CONFIG)
popup_shown = False


def now() -> datetime:
    return datetime.now(timezone.utc)


def read_config() -> dict:
    """Settings as whole minutes; a bad value falls back to its default with a warning."""
    out = {}
    for name, (key, low, high, default) in SETTINGS.items():
        raw = app.settings.get(name, default)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = -1
        if not low <= value <= high:
            app.log("warn", f"{name} must be a whole number from {low} to {high}; using {default}", value=raw)
            value = default
        out[key] = value
    return out


def load_state() -> None:
    try:
        saved = json.loads((app.data_dir / STATE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        app.log("warn", "state.json is unreadable; starting idle", error=str(exc))
        return
    state.update({key: saved[key] for key in state if key in saved})


def save_state() -> None:
    path = app.data_dir / STATE_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, path)


def render() -> None:
    at = now()
    app.render(TILE, "tile", views.tile(state, at, app.t))
    app.render(TILE, "hover", views.hover(state, at, app.t))
    app.render(TILE, "flyout", views.flyout(state, at, config, app.t))


def commit() -> None:
    save_state()
    render()


def dismiss_popup() -> None:
    global popup_shown
    if popup_shown and "popups" in app.capabilities:
        app.popups.dismiss(TILE, POPUP)
    popup_shown = False


def write_chime(path) -> None:
    """A soft two-tone chime (E5, then A5), 0.6 s, 44.1 kHz, 16-bit mono, faded out."""
    rate, total = 44100, 0.6
    notes = ((659.25, 0.0), (880.0, 0.26))  # (frequency, onset seconds)
    samples = array.array("h")
    for i in range(int(rate * total)):
        t = i / rate
        value = 0.0
        for freq, onset in notes:
            dt = t - onset
            if dt >= 0:
                envelope = min(1.0, dt / 0.012) * math.exp(-4.0 * dt)
                value += envelope * (math.sin(2 * math.pi * freq * dt) + 0.2 * math.sin(4 * math.pi * freq * dt))
        fade = min(1.0, (total - t) / 0.15)
        samples.append(int(max(-1.0, min(1.0, 0.3 * value * fade)) * 32767))
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    os.replace(tmp, path)


def ensure_chime() -> None:
    path = app.data_dir / CHIME_FILE
    if path.exists():
        return
    try:
        write_chime(path)
    except OSError as exc:
        app.log("warn", "could not write the chime; phases end silently", error=str(exc))


def phase_ended(ended: str) -> None:
    """Popup with the next step and, unless switched off, the chime."""
    global popup_shown
    if "popups" in app.capabilities:
        result = app.popups.show(
            TILE, POPUP, views.popup(ended, state, config, app.t), ttl_ms=POPUP_TTL_MS
        )
        popup_shown = result.get("state") == "accepted"
        if not popup_shown:
            app.log("info", "done popup not accepted", ended=ended, result=str(result))
    if app.settings.get("sound", True) and "audio" in app.capabilities:
        try:
            app.audio.play("chime", {"root": "data", "path": CHIME_FILE})
        except RpcError as exc:
            app.log("warn", "chime did not play", error=str(exc))


def clean_label(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_LABEL:
        raise ValueError(f"label must be a string of at most {MAX_LABEL} characters")
    return value.strip()


@app.on_ready
def ready() -> None:
    global config
    config = read_config()
    load_state()
    # Reconcile: a phase that ended while the bar was away is counted and the
    # next one waits pending — no popup, no chime, no auto-run chain.
    model.tick(state, config, now())
    ensure_chime()
    commit()


@app.every(1)
def tick() -> None:
    day = state["dayKey"]
    ended = model.tick(state, config, now())
    if ended:
        commit()
        phase_ended(ended)
    elif state["dayKey"] != day:
        commit()


@app.popups.on_event
def popup_event(event: dict) -> None:
    """Delivery of the done popup: once the user closed it, there is nothing left to dismiss."""
    global popup_shown
    if event.get("popupId") != POPUP:
        return
    delivery = event.get("state")
    app.log("info", "done popup", state=delivery, reason=event.get("reason"))
    if delivery in ("dismissed", "expired", "dropped", "suppressed"):
        popup_shown = False


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    global config
    config = read_config()
    model.apply_config(state, config)
    commit()


def on_skip(value: object) -> None:
    at = now()
    model.skip(state, config, at)
    if value == "start":  # the popup's "Skip break" goes straight into the next focus
        model.start(state, config, at)


def on_extend(value: object) -> None:
    if value not in model.PHASES:
        raise ValueError(f"extend needs a phase, got {value!r}")
    model.extend(state, now(), str(value))


PHASE_ACTIONS = {
    "start": lambda value: model.start(state, config, now()),
    "pause": lambda value: model.pause(state, now()),
    "resume": lambda value: model.resume(state, now()),
    "skip": on_skip,
    "reset": lambda value: model.reset(state),
    "extend": on_extend,
}


@app.on_action(TILE)
def on_action(name: str, value: object) -> None:
    if name == "save_label":
        fields = value if isinstance(value, dict) else {}
        state["label"] = clean_label(fields.get("label", ""))
        commit()
        return
    handler = PHASE_ACTIONS.get(name)
    if handler is None:
        return  # the shell also reports plain tile clicks ("tile") here; nothing to do
    handler(value)
    dismiss_popup()
    commit()


def changed() -> dict:
    dismiss_popup()
    commit()
    return model.status(state, now())


@app.command(
    "start",
    description="Start a focus block now, optionally with a custom length in minutes and a label. Fails while a phase is running.",
    input_schema={
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "minimum": 1, "maximum": MAX_MINUTES},
            "label": {"type": "string", "maxLength": MAX_LABEL},
        },
        "additionalProperties": False,
    },
    output_schema=STATUS_SCHEMA,
)
def cmd_start(args: dict) -> dict:
    minutes = args.get("minutes")
    if minutes is not None and (
        isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= MAX_MINUTES
    ):
        raise ValueError(f"minutes must be an integer from 1 to {MAX_MINUTES}")
    label = clean_label(args["label"]) if "label" in args else None
    model.start_focus(state, config, now(), minutes)
    if label is not None:
        state["label"] = label
    return changed()


@app.command("pause", description="Pause the running phase.", input_schema=NO_INPUT, output_schema=STATUS_SCHEMA)
def cmd_pause(args: dict) -> dict:
    if not model.is_running(state):
        raise ValueError("nothing is running")
    model.pause(state, now())
    return changed()


@app.command("resume", description="Resume a paused or pending phase.", input_schema=NO_INPUT, output_schema=STATUS_SCHEMA)
def cmd_resume(args: dict) -> dict:
    if not model.is_paused(state):
        raise ValueError("nothing is paused")
    model.resume(state, now())
    return changed()


@app.command(
    "skip",
    description="Move to the next phase; a running phase keeps running, a paused one waits pending.",
    input_schema=NO_INPUT,
    output_schema=STATUS_SCHEMA,
)
def cmd_skip(args: dict) -> dict:
    if state["phase"] == model.IDLE:
        raise ValueError("nothing to skip: the timer is idle")
    model.skip(state, config, now())
    return changed()


@app.command("stop", description="Stop the timer and go back to idle; today's counters stay.", input_schema=NO_INPUT, output_schema=STATUS_SCHEMA)
def cmd_stop(args: dict) -> dict:
    model.reset(state)
    return changed()


@app.command("status", description="The current phase, remaining seconds and today's totals.", input_schema=NO_INPUT, output_schema=STATUS_SCHEMA)
def cmd_status(args: dict) -> dict:
    return model.status(state, now())


if __name__ == "__main__":
    app.run()
