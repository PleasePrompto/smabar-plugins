"""Pomodoro state machine on a plain dict — no bar imports, so test_timer.py runs alone.

The dict is what plugin.py persists as JSON: phase, endsAt (ISO, UTC) while a
phase runs, pausedRemainingSeconds while it is paused, phaseSeconds (the length
the current phase started with), extension (a "+5 min" block that adds focus
minutes but no completed block), the day counters and the focus label.
A phase paused at its full length is "pending": it waits for Start.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

IDLE = "idle"
FOCUS = "focus"
SHORT_BREAK = "short_break"
LONG_BREAK = "long_break"
PHASES = (FOCUS, SHORT_BREAK, LONG_BREAK)
EXTEND_SECONDS = 300

# Minutes per phase and the long-break interval; plugin.py fills it from settings.
DEFAULT_CONFIG = {"focus": 25, "shortBreak": 5, "longBreak": 15, "longBreakEvery": 4}
CONFIG_KEY = {FOCUS: "focus", SHORT_BREAK: "shortBreak", LONG_BREAK: "longBreak"}


def new_state() -> dict:
    return {
        "phase": IDLE,
        "endsAt": None,
        "pausedRemainingSeconds": None,
        "phaseSeconds": 0,
        "extension": False,
        "completedToday": 0,
        "focusMinutesToday": 0,
        "dayKey": "",
        "label": "",
    }


def day_key(now: datetime) -> str:
    """The local calendar day; the counters reset when it changes."""
    return now.astimezone().date().isoformat()


def is_running(state: dict) -> bool:
    return state["endsAt"] is not None


def is_paused(state: dict) -> bool:
    return state["pausedRemainingSeconds"] is not None


def is_pending(state: dict) -> bool:
    return is_paused(state) and state["pausedRemainingSeconds"] == state["phaseSeconds"]


def ends_at(state: dict) -> datetime:
    return datetime.fromisoformat(state["endsAt"])


def remaining_seconds(state: dict, now: datetime) -> int:
    if is_running(state):
        return max(0, math.ceil((ends_at(state) - now).total_seconds()))
    return state["pausedRemainingSeconds"] or 0


def phase_seconds(config: dict, phase: str) -> int:
    return int(config[CONFIG_KEY[phase]]) * 60


def break_after(completed: int, config: dict) -> str:
    """The break that follows the given number of completed blocks."""
    every = max(1, int(config["longBreakEvery"]))
    return LONG_BREAK if completed > 0 and completed % every == 0 else SHORT_BREAK


def next_phase(state: dict, config: dict) -> str:
    if state["phase"] != FOCUS:
        return FOCUS
    counted = state["completedToday"] + (0 if state["extension"] else 1)
    return break_after(counted, config)


def _run(state: dict, now: datetime, seconds: int) -> None:
    state["endsAt"] = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    state["pausedRemainingSeconds"] = None


def _enter(state: dict, phase: str, seconds: int, now: datetime, *, running: bool) -> None:
    state.update({"phase": phase, "phaseSeconds": seconds, "extension": False})
    if running:
        _run(state, now, seconds)
    else:
        state["endsAt"] = None
        state["pausedRemainingSeconds"] = seconds


def start(state: dict, config: dict, now: datetime) -> None:
    """The Start button: idle begins a focus block, a paused or pending phase resumes."""
    if state["phase"] == IDLE:
        _enter(state, FOCUS, phase_seconds(config, FOCUS), now, running=True)
    else:
        resume(state, now)


def start_focus(state: dict, config: dict, now: datetime, minutes: int | None = None) -> None:
    """The agent command: a focus block now; it never replaces a running phase."""
    if is_running(state):
        raise ValueError("a phase is already running; pause, skip or stop it first")
    _enter(state, FOCUS, (minutes or config["focus"]) * 60, now, running=True)


def pause(state: dict, now: datetime) -> None:
    if is_running(state):
        state["pausedRemainingSeconds"] = remaining_seconds(state, now)
        state["endsAt"] = None


def resume(state: dict, now: datetime) -> None:
    if is_paused(state):
        _run(state, now, state["pausedRemainingSeconds"])


def skip(state: dict, config: dict, now: datetime) -> None:
    """Move to the next phase: a running phase keeps running, a paused one waits pending."""
    # ponytail: a skipped focus block counts nothing, however far it got.
    if state["phase"] == IDLE:
        return
    following = next_phase(state, config)
    _enter(state, following, phase_seconds(config, following), now, running=is_running(state))


def reset(state: dict) -> None:
    """Back to idle; the day counters and the label stay."""
    state.update(
        {"phase": IDLE, "endsAt": None, "pausedRemainingSeconds": None, "phaseSeconds": 0, "extension": False}
    )


def extend(state: dict, now: datetime, phase: str, seconds: int = EXTEND_SECONDS) -> None:
    """'+5 min' on the done popup: a short extra block of the phase that just ended."""
    _enter(state, phase, seconds, now, running=True)
    state["extension"] = True


def tick(state: dict, config: dict, now: datetime) -> str | None:
    """Finish a phase whose end has passed and roll the day counters.

    Returns the phase that ended, or None. The next phase is entered pending,
    never running, so a restart after hours away does not replay a whole chain.
    """
    ended = None
    if is_running(state) and ends_at(state) <= now:
        ended = state["phase"]
        if ended == FOCUS:
            state["focusMinutesToday"] += state["phaseSeconds"] // 60
            if not state["extension"]:
                state["completedToday"] += 1
        following = break_after(state["completedToday"], config) if ended == FOCUS else FOCUS
        _enter(state, following, phase_seconds(config, following), now, running=False)
    today = day_key(now)
    if state["dayKey"] != today:
        state.update({"completedToday": 0, "focusMinutesToday": 0, "dayKey": today})
    return ended


def apply_config(state: dict, config: dict) -> None:
    """A pending phase takes the new length; a running or half-done one keeps its own."""
    if state["phase"] != IDLE and is_pending(state):
        seconds = phase_seconds(config, state["phase"])
        state.update({"phaseSeconds": seconds, "pausedRemainingSeconds": seconds})


def status(state: dict, now: datetime) -> dict:
    """What the agent commands return."""
    return {
        "phase": state["phase"],
        "running": is_running(state),
        "remainingSeconds": remaining_seconds(state, now),
        "endsAt": state["endsAt"],
        "label": state["label"],
        "completedToday": state["completedToday"],
        "focusMinutesToday": state["focusMinutesToday"],
    }
