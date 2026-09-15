# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Docker: the local containers on the bar, with start, stop and restart.

One worker thread runs `<binary> ps -a` (and `stats` when enabled) and loops
on the refreshSeconds setting; a manual refresh, a finished action or a
settings change wakes it early. Actions run on their own thread and never
block the handler lock. Nothing is cached on disk: ps answers in
milliseconds, so the tile is filled right after start.
"""

import threading
import time

import engine
import views
from smabar_sdk import Plugin, RpcError

app = Plugin()
TILE = "containers"
DEFAULT_BINARY = "docker"
DEFAULT_INTERVAL = 10
MIN_INTERVAL = 3
ACTION_TIMEOUT = 30
STATS_TIMEOUT = 20
POPUP_MS = 8000
ENGINE_FAILED = -32002

state: dict = {
    "containers": [],
    "phase": "loading",
    "error": "",
    "version": "",
    "updated": "",
    "busy": set(),
}
lock = threading.Lock()
wake = threading.Event()
reported: dict[str, str] = {"ps": "", "stats": ""}  # what is already in the log


# --- settings ------------------------------------------------------------


def binary() -> str:
    value = app.settings.get("binary")
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_BINARY


def interval() -> int:
    try:
        return max(MIN_INTERVAL, int(float(app.settings.get("refreshSeconds", DEFAULT_INTERVAL))))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def show_stats() -> bool:
    return app.settings.get("showStats", True) is not False


def check_settings() -> None:
    """A bad refreshSeconds falls back; say so once instead of on every loop."""
    raw = app.settings.get("refreshSeconds", DEFAULT_INTERVAL)
    try:
        if float(raw) < MIN_INTERVAL:
            app.log("warn", f"refreshSeconds is below {MIN_INTERVAL}; using {MIN_INTERVAL}", value=raw)
    except (TypeError, ValueError):
        app.log("warn", f"refreshSeconds is not a number; using {DEFAULT_INTERVAL}", value=repr(raw))


# --- rendering -----------------------------------------------------------


def render() -> None:
    """Push every surface from a snapshot of the state; safe from any thread."""
    with lock:
        snapshot = {**state, "busy": set(state["busy"])}
    name = engine.engine_name(binary())
    app.render(TILE, "tile", views.tile(snapshot, name, app.t))
    app.render(TILE, "hover", views.hover(snapshot, name, app.t))
    app.render(TILE, "flyout", views.flyout(snapshot, name, binary(), interval(), show_stats(), app.t))


def note(kind: str, message: str, error: str, **fields: object) -> None:
    """Log a recurring failure once, until it changes or clears."""
    if reported[kind] != error:
        reported[kind] = error
        app.log("warn", message, error=error, **fields)


# --- worker --------------------------------------------------------------


def detect_version(program: str) -> str:
    for command in engine.version_commands(program):
        try:
            return engine.run(command).strip()
        except engine.EngineError:
            continue
    return ""


def refresh_once() -> None:
    program = binary()
    try:
        containers = engine.parse_ps(engine.run(engine.ps_command(program)))
    except (engine.EngineError, ValueError) as error:
        with lock:
            state["phase"] = "missing" if isinstance(error, engine.EngineMissing) else "offline"
            state["error"] = str(error)
        note("ps", "container list unavailable; keeping the last one", str(error), binary=program,
             hint="start the engine or fix the binary setting")
        render()
        return
    reported["ps"] = ""
    if not state["version"]:
        version = detect_version(program)
        with lock:
            state["version"] = version
        app.log("info", "engine detected", engine=engine.engine_name(program), version=version or "unknown")
    with lock:
        state.update(containers=containers, phase="ok", error="", updated=time.strftime("%H:%M"))
    render()
    if not show_stats() or not any(item.running for item in containers):
        return
    try:
        stats = engine.parse_stats(engine.run(engine.stats_command(program), timeout=STATS_TIMEOUT))
    except engine.EngineError as error:
        note("stats", "container stats unavailable", str(error), hint="disable showStats to skip them")
        return
    reported["stats"] = ""
    with lock:
        state["containers"] = engine.with_stats(state["containers"], stats)
    render()


def worker() -> None:
    while True:
        refresh_once()
        wake.wait(interval())
        wake.clear()


# --- actions -------------------------------------------------------------


def container_name(target: str) -> str:
    with lock:
        return next((c.name for c in state["containers"] if target in (c.id, c.name)), target)


def run_action(action: str, target: str, command: list[str], via: str) -> str:
    """Run one start/stop/restart and log it with its outcome, so every change
    made through this plugin is traceable; returns the engine's error or ""."""
    try:
        engine.run(command, timeout=ACTION_TIMEOUT)
    except engine.EngineError as error:
        app.log("error", "container action failed", action=action, container=target,
                name=container_name(target), via=via, outcome="failed", error=str(error))
        return str(error)
    app.log("info", "container action done", action=action, container=target,
            name=container_name(target), via=via, outcome="ok")
    return ""


def control(action: str, target: str, command: list[str]) -> None:
    """Action thread for the flyout buttons: run, report a failure as a popup, refresh."""
    try:
        error = run_action(action, target, command, via="flyout")
        if error and "popups" in app.capabilities:
            label = views.tr(app.t, f"docker.{action}", name=container_name(target))
            app.popups.show(TILE, f"failed-{target}", views.failure(label, error, app.t), ttl_ms=POPUP_MS)
    finally:
        with lock:
            state["busy"].discard(target)
    wake.set()


def start_control(action: str, target: str) -> None:
    try:
        command = engine.action_command(binary(), action, target)
    except ValueError as error:
        app.log("warn", "ignoring a container action", action=action, target=target[:64], error=str(error))
        return
    with lock:
        if target in state["busy"]:
            return
        state["busy"].add(target)
    render()
    threading.Thread(target=control, args=(action, target, command), daemon=True).start()


@app.on_action(TILE)
def on_action(action: str, value: object) -> None:
    if action == "refresh":
        wake.set()
    elif action in engine.ACTIONS:
        start_control(action, str(value))


# --- agent commands ------------------------------------------------------

CONTAINER = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "image": {"type": "string"},
        "state": {"type": "string", "description": "running, exited, created, paused, …"},
        "since": {"type": "string", "description": "Compact age of that state, e.g. \"4 h\""},
        "exitCode": {"type": ["integer", "null"]},
        "health": {"type": "string", "description": "healthy, unhealthy, starting or empty"},
        "ports": {"type": "array", "items": {"type": "string"}, "description": "host→container"},
        "project": {"type": "string", "description": "Compose project, empty when standalone"},
        "cpuPercent": {"type": ["number", "null"]},
        "memoryPercent": {"type": ["number", "null"]},
        "memory": {"type": "string"},
    },
    "required": ["id", "name", "image", "state", "ports", "project"],
}


def as_dict(item: engine.Container) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "image": item.image,
        "state": item.state,
        "since": item.since,
        "exitCode": item.exit_code,
        "health": item.health,
        "ports": list(item.ports),
        "project": item.project,
        "cpuPercent": item.cpu,
        "memoryPercent": item.mem,
        "memory": item.mem_text,
    }


@app.command(
    "list",
    description="The containers of the configured engine as last read: state, ports, compose "
    "project and, when showStats is on, CPU and memory of the running ones.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {
            "engine": {"type": "string"},
            "version": {"type": "string"},
            "phase": {"type": "string", "enum": ["loading", "ok", "offline", "missing"]},
            "error": {"type": "string"},
            "running": {"type": "integer"},
            "total": {"type": "integer"},
            "containers": {"type": "array", "items": CONTAINER},
        },
        "required": ["engine", "phase", "running", "total", "containers"],
    },
)
def list_containers(arguments: dict) -> dict:
    with lock:
        containers = list(state["containers"])
        phase, error, version = state["phase"], state["error"], state["version"]
    running, total = engine.counts(containers)
    return {
        "engine": engine.engine_name(binary()),
        "version": version,
        "phase": phase,
        "error": error,
        "running": running,
        "total": total,
        "containers": [as_dict(item) for item in containers],
    }


def register_control(action: str) -> None:
    @app.command(
        action,
        description=f"{action.capitalize()} one container by name or id and wait for the engine's answer "
        f"(up to {ACTION_TIMEOUT} s).",
        input_schema={
            "type": "object",
            "properties": {"container": {"type": "string", "description": "Container name or id"}},
            "required": ["container"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "container": {"type": "string"}},
            "required": ["ok", "container"],
        },
    )
    def handle(arguments: dict) -> dict:
        target = arguments.get("container")
        if not isinstance(target, str):
            raise ValueError("container must be a string")
        target = target.strip()
        command = engine.action_command(binary(), action, target)
        error = run_action(action, target, command, via="command")
        if error:
            raise RpcError(ENGINE_FAILED, error)
        wake.set()
        return {"ok": True, "container": target}


for name in engine.ACTIONS:
    register_control(name)


# --- lifecycle -----------------------------------------------------------


@app.on_ready
def ready() -> None:
    check_settings()
    render()
    threading.Thread(target=worker, daemon=True).start()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    check_settings()
    with lock:
        state["version"] = ""  # the binary may have changed; the worker detects it again
    render()
    wake.set()


if __name__ == "__main__":
    app.run()
