# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Uptime: is it up? Your own sites, servers and services, checked from this machine.

checks.py holds the target parser, the probes and the state machine (no SDK),
views.py the markup. This file is the glue: settings, the state file, the
check rounds on a worker thread, popups on state changes and agent commands.
"""

import hashlib
import json
import os
import threading
import time

import checks
import views
from smabar_sdk import Plugin

app = Plugin()
TILE = "status"
STATE_FILE = "state.json"
# setting: (default, minimum, maximum)
LIMITS = {
    "intervalSeconds": (60, 15, 86400),
    "timeoutSeconds": (5, 1, 60),
    "historySize": (60, 5, 1000),
    "failuresBeforeDown": (2, 1, 100),
}
DOWN_POPUP_MS = 60000
UP_POPUP_MS = 15000

# Everything the surfaces show. Handlers and the worker mutate it under
# state_lock; render() reads a snapshot. round_lock serializes check rounds.
state: dict = {
    "targets": [],  # list[checks.Target] in settings order
    "rejected": [],  # list[checks.TargetError] for skipped settings entries
    "entries": {},  # spec -> {status, since, fails, history}
    "next_at": 0.0,
    "busy": False,
    "rounds": 0,
    "form_error": "",
    "form_epoch": 0,
}
state_lock = threading.Lock()
round_lock = threading.Lock()


# --- settings ----------------------------------------------------------------


def setting(key: str) -> int:
    """A numeric setting clamped to its range; a bad value falls back."""
    default, low, high = LIMITS[key]
    raw = app.settings.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        app.log("warn", f"{key} is not a number; using {default}", value=repr(raw)[:40])
        return default
    return min(high, max(low, value))


def raw_targets() -> list[object]:
    raw = app.settings.get("targets", [])
    if not isinstance(raw, list):
        app.log("warn", "targets is not a list; using none", value=repr(raw)[:60])
        return []
    return raw


def apply_settings() -> None:
    """Parse the configured targets and drop the state of removed ones."""
    targets, rejected = checks.parse_targets(raw_targets())
    if rejected:
        app.log(
            "warn",
            "skipped settings entries",
            entries=[f"{error.code}: {error.entry}" for error in rejected],
            hint="targets are 'Name | target' or a target: https://…, tcp://host:port, ping:host",
        )
    keep = {target.spec for target in targets}
    with state_lock:
        state["targets"], state["rejected"] = targets, rejected
        state["entries"] = {
            spec: entry for spec, entry in state["entries"].items() if spec in keep
        }


def find_target(key: str) -> checks.Target | None:
    """A configured target by name (case-insensitive) or by its target string."""
    wanted = key.strip().casefold()
    with state_lock:
        targets = list(state["targets"])
    for target in targets:
        if wanted in (target.name.casefold(), target.spec.casefold()):
            return target
    return None


def add_target(name: str, spec: str) -> checks.Target:
    """Append 'Name | target' to the settings; raises checks.TargetError."""
    entry = f"{name} | {spec}" if name else spec
    current = raw_targets()
    targets, rejected = checks.parse_targets([*current, entry])
    for error in rejected:
        if error.entry == entry:
            raise error
    # set_settings REPLACES the whole settings object: spread the current ones.
    app.set_settings({**app.settings, "targets": [*current, entry]})
    app.log("info", "target added", target=targets[-1].name, spec=targets[-1].spec)
    return targets[-1]


def keeps(raw: object, target: checks.Target) -> bool:
    if not isinstance(raw, str):
        return True
    try:
        return checks.parse_target(raw).spec != target.spec
    except checks.TargetError:
        return True


def remove_target(target: checks.Target) -> None:
    kept = [raw for raw in raw_targets() if keeps(raw, target)]
    app.set_settings({**app.settings, "targets": kept})
    app.log("info", "target removed", target=target.name, spec=target.spec)


# --- state file --------------------------------------------------------------


def load_state() -> dict[str, dict]:
    path = app.data_dir / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        app.log("warn", "ignoring an unreadable state file", file=path.name, error=str(error))
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {
        spec: checks.restore_entry(entry)
        for spec, entry in entries.items()
        if isinstance(spec, str)
    }


def save_state(payload: str) -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    path = app.data_dir / STATE_FILE
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        app.log("warn", "could not save the check history", error=str(error))


# --- rows and rendering ------------------------------------------------------


def describe(target: checks.Target, entry: dict, now: float) -> dict:
    """One target as the surfaces and the agent commands see it."""
    history = entry["history"]
    last = history[-1] if history else None
    uptime = checks.uptime_percent(history)
    since = entry["since"]
    return {
        "name": target.name,
        "target": target.spec,
        "host": target.where,
        "status": entry["status"],
        "latencyMs": last["ms"] if last is not None and last["ok"] else None,
        "uptimePercent": None if uptime is None else round(uptime, 1),
        "reason": "" if last is None or last["ok"] else last["code"],
        "since": since,
        "sinceSeconds": None if since is None else max(0, int(now) - since),
        "checks": len(history),
        "points": [sample["ms"] for sample in history if sample["ok"]],
    }


def rows_for(targets: list[checks.Target]) -> list[dict]:
    now = time.time()
    with state_lock:
        return [
            describe(target, state["entries"].get(target.spec) or checks.new_entry(), now)
            for target in targets
        ]


def render() -> None:
    """Push every surface from the current state; safe from any thread."""
    with state_lock:
        targets = list(state["targets"])
        problems = [views.problem(error.code, error.entry, app.t) for error in state["rejected"]]
        checking, next_at = state["busy"], state["next_at"]
        form_error, epoch = state["form_error"], state["form_epoch"]
    rows = rows_for(targets)
    app.render(TILE, "tile", views.tile(rows, app.t))
    app.render(TILE, "hover", views.hover(rows, app.t))
    app.render(
        TILE,
        "flyout",
        views.flyout(
            rows,
            problems=problems,
            next_iso=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(next_at)),
            checking=checking,
            form_error=form_error,
            epoch=epoch,
            interval=setting("intervalSeconds"),
            t=app.t,
        ),
    )


# --- check rounds ------------------------------------------------------------


def popup_id(prefix: str, target: checks.Target) -> str:
    return f"{prefix}-{hashlib.sha1(target.spec.encode('utf-8')).hexdigest()[:12]}"


def notify(target: checks.Target, sample: dict, change: str, since_before: int | None) -> None:
    if change == "down":
        text = views.tr(
            app.t, "uptime.popup.down", name=target.name, reason=views.reason(sample["code"], app.t)
        )
        shown = app.popups.show(TILE, popup_id("down", target), views.popup("down", text, app.t), ttl_ms=DOWN_POPUP_MS)
        app.log("debug", "popup requested", target=target.name, change=change, state=shown.get("state"))
        return
    app.popups.dismiss(TILE, popup_id("down", target))
    outage = views.duration(sample["t"] - (since_before or sample["t"]), app.t)
    text = views.tr(app.t, "uptime.popup.up", name=target.name, duration=outage)
    shown = app.popups.show(TILE, popup_id("up", target), views.popup("up", text, app.t), ttl_ms=UP_POPUP_MS)
    app.log("debug", "popup requested", target=target.name, change=change, state=shown.get("state"))


def run_round(targets: list[checks.Target] | None = None) -> list[dict]:
    """Probe the targets (all configured ones by default), record the samples,
    save, notify state changes and render. Rounds never overlap; runs on the
    calling thread and returns the rows of the checked targets."""
    with round_lock:
        with state_lock:
            chosen = list(state["targets"]) if targets is None else list(targets)
            first = state["rounds"] == 0
            state["busy"] = True
        render()
        samples = checks.probe_all(chosen, setting("timeoutSeconds"))
        events = []
        with state_lock:
            for target, sample in zip(chosen, samples, strict=True):
                entry = state["entries"].setdefault(target.spec, checks.new_entry())
                since_before = entry["since"]
                change = checks.apply(
                    entry,
                    sample,
                    history_size=setting("historySize"),
                    threshold=setting("failuresBeforeDown"),
                )
                if change:
                    events.append((target, sample, change, since_before))
            state["busy"] = False
            state["rounds"] += 1
            if targets is None:
                state["next_at"] = time.time() + setting("intervalSeconds")
            payload = json.dumps({"entries": state["entries"]})
        save_state(payload)
        for target, sample, change, since_before in events:
            app.log("info", "status changed", target=target.name, status=change, code=sample["code"])
            # The first round of a process reports the state, it does not announce it.
            if not first and "popups" in app.capabilities:
                notify(target, sample, change, since_before)
        render()
        return rows_for(chosen)


def start_round() -> None:
    """A full round on a worker thread; a round already running is left alone."""
    with state_lock:
        if state["busy"]:
            return
        state["busy"] = True
    threading.Thread(target=run_round, daemon=True).start()


# --- lifecycle and actions ---------------------------------------------------


@app.on_ready
def ready() -> None:
    """Settings and locales exist from here on: show the saved state, then check."""
    with state_lock:
        state["entries"] = load_state()
    apply_settings()
    render()
    start_round()


@app.every(1)
def tick() -> None:
    with state_lock:
        due = not state["busy"] and time.time() >= state["next_at"]
    if due:
        start_round()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    apply_settings()
    start_round()


@app.on_action(TILE, "check")
def on_check(action: str, value: object) -> None:
    start_round()


@app.on_action(TILE, "add")
def on_add(action: str, value: object) -> None:
    """The form's fields arrive as a dict keyed by data-field."""
    fields = value if isinstance(value, dict) else {}
    with state_lock:
        epoch = state["form_epoch"]
    name = str(fields.get(f"name-{epoch}", "")).strip()
    spec = str(fields.get(f"target-{epoch}", "")).strip()
    error = ""
    if not spec:
        error = app.t("uptime.targetRequired")
    else:
        try:
            add_target(name, spec)
        except checks.TargetError as problem:
            error = views.problem(problem.code, problem.entry, app.t)
    with state_lock:
        state["form_error"] = error
        if not error:
            state["form_epoch"] = epoch + 1
    if error:
        render()
    # On success the core answers with settings.changed; settings_changed()
    # renders and starts the round that checks the new target.


@app.on_action(TILE, "remove")
def on_remove(action: str, value: object) -> None:
    target = find_target(str(value))
    if target is not None:
        remove_target(target)


# --- agent commands ----------------------------------------------------------

ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "target": {"type": "string"},
        "host": {"type": "string"},
        "status": {"enum": list(checks.STATUSES)},
        "latencyMs": {"type": ["integer", "null"], "description": "Latency of the last check when it succeeded"},
        "uptimePercent": {"type": ["number", "null"], "description": "Successful share of the checks in the history buffer"},
        "reason": {"type": "string", "description": "Empty when up; otherwise an HTTP status or timeout, dns, refused, tls, error"},
        "since": {"type": ["integer", "null"], "description": "Unix seconds of the last state change"},
        "sinceSeconds": {"type": ["integer", "null"]},
        "checks": {"type": "integer", "description": "Samples in the history buffer"},
        "points": {"type": "array", "items": {"type": "integer"}, "description": "Latency in ms of the successful checks, oldest first"},
    },
}
ROWS_SCHEMA = {
    "type": "object",
    "properties": {"targets": {"type": "array", "items": ROW_SCHEMA}},
    "required": ["targets"],
}


@app.command(
    "status",
    description="Every configured target with its state, latest latency, uptime and the time of its last state change.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        **ROWS_SCHEMA,
        "properties": {
            **ROWS_SCHEMA["properties"],
            "nextCheckAt": {"type": "integer", "description": "Unix seconds of the next scheduled round"},
        },
    },
)
def cmd_status(arguments: dict) -> dict:
    with state_lock:
        targets, next_at = list(state["targets"]), state["next_at"]
    return {"targets": rows_for(targets), "nextCheckAt": int(next_at)}


@app.command(
    "check",
    description="Check every target now, or one target by name, and return the results.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "A target's name or target string; omit for all"}},
        "additionalProperties": False,
    },
    output_schema=ROWS_SCHEMA,
)
def cmd_check(arguments: dict) -> dict:
    name = arguments.get("name")
    if name is None:
        return {"targets": run_round()}
    target = find_target(str(name))
    if target is None:
        raise ValueError(f"no target named {name!r}; call status for the list")
    # ponytail: runs on the handler thread, so the reply waits for the probe
    # (at most timeoutSeconds, twice that for ping:).
    return {"targets": run_round([target])}


@app.command(
    "add",
    description="Add a target: https://…, http://…, tcp://host:port or ping:host, with an optional name. The first check runs right away; call status a few seconds later.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 60},
            "target": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["target"],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"name": {"type": "string"}, "target": {"type": "string"}}, "required": ["name", "target"]},
)
def cmd_add(arguments: dict) -> dict:
    name, spec = arguments.get("name", ""), arguments.get("target", "")
    if not isinstance(name, str) or not isinstance(spec, str) or not spec.strip():
        raise ValueError("target must be a non-empty string; name is an optional string")
    if "|" in name:
        raise ValueError("name must not contain '|'")
    try:
        target = add_target(name.strip(), spec.strip())
    except checks.TargetError as error:
        raise ValueError(views.problem(error.code, error.entry, app.t)) from error
    return {"name": target.name, "target": target.spec}


@app.command(
    "remove",
    description="Remove a target by its name or target string.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1}},
        "required": ["name"],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"removed": {"type": "string"}}, "required": ["removed"]},
)
def cmd_remove(arguments: dict) -> dict:
    name = arguments.get("name")
    target = find_target(str(name)) if isinstance(name, str) else None
    if target is None:
        raise ValueError(f"no target named {name!r}; call status for the list")
    remove_target(target)
    return {"removed": target.name}


if __name__ == "__main__":
    # Guarded so test_checks.py can import this module without the RPC loop.
    app.run()
