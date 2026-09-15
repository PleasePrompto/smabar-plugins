# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the Pomodoro state machine. Run: python3 test_timer.py"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import model  # noqa: E402

CONFIG = dict(model.DEFAULT_CONFIG)
T0 = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)


def at(minutes: float, base: datetime = T0) -> datetime:
    return base + timedelta(minutes=minutes)


def fresh() -> dict:
    state = model.new_state()
    model.tick(state, CONFIG, T0)  # sets today's dayKey
    return state


# Idle → focus: Start runs a full focus block.
s = fresh()
assert s["phase"] == model.IDLE and not model.is_running(s)
model.start(s, CONFIG, T0)
assert s["phase"] == model.FOCUS and model.is_running(s)
assert model.remaining_seconds(s, T0) == 1500
assert model.next_phase(s, CONFIG) == model.SHORT_BREAK

# The end of the block is only reached once endsAt has passed.
assert model.tick(s, CONFIG, at(24.9)) is None
assert s["phase"] == model.FOCUS
assert model.tick(s, CONFIG, at(25)) == model.FOCUS
assert s["completedToday"] == 1 and s["focusMinutesToday"] == 25
# The break waits pending: paused at its full length, nothing runs on its own.
assert s["phase"] == model.SHORT_BREAK and model.is_pending(s) and not model.is_running(s)
assert model.remaining_seconds(s, at(25)) == 300
model.start(s, CONFIG, at(26))
assert model.is_running(s) and model.remaining_seconds(s, at(26)) == 300
assert model.tick(s, CONFIG, at(31)) == model.SHORT_BREAK
assert s["phase"] == model.FOCUS and model.is_pending(s)
assert s["completedToday"] == 1, "a break never counts as a block"

# The fourth focus block is followed by the long break, the fifth by a short one again.
s = fresh()
clock = T0
for block in range(1, 6):
    model.start(s, CONFIG, clock)
    if block == 4:
        assert model.next_phase(s, CONFIG) == model.LONG_BREAK
    clock = clock + timedelta(minutes=25)
    assert model.tick(s, CONFIG, clock) == model.FOCUS
    expected = model.LONG_BREAK if block == 4 else model.SHORT_BREAK
    assert s["phase"] == expected, (block, s["phase"])
    assert s["completedToday"] == block
    model.skip(s, CONFIG, clock)  # skip the pending break: the next focus waits pending
    assert s["phase"] == model.FOCUS and model.is_pending(s)
assert s["focusMinutesToday"] == 125

# Pause keeps the remaining time; resume continues from exactly there.
s = fresh()
model.start(s, CONFIG, T0)
model.pause(s, at(10))
assert not model.is_running(s) and s["pausedRemainingSeconds"] == 900
assert model.remaining_seconds(s, at(40)) == 900, "time does not pass while paused"
assert model.tick(s, CONFIG, at(60)) is None
model.resume(s, at(60))
assert model.is_running(s) and model.remaining_seconds(s, at(60)) == 900
assert model.tick(s, CONFIG, at(74.9)) is None
assert model.tick(s, CONFIG, at(75)) == model.FOCUS
model.pause(s, at(76))  # pausing a pending phase changes nothing
assert model.is_pending(s)

# Skip while running keeps running; the first break comes after one block.
s = fresh()
model.start(s, CONFIG, T0)
model.skip(s, CONFIG, at(3))
assert s["phase"] == model.SHORT_BREAK and model.is_running(s)
assert model.remaining_seconds(s, at(3)) == 300
assert s["completedToday"] == 0, "a skipped block does not count"
model.skip(s, CONFIG, at(4))
assert s["phase"] == model.FOCUS and model.is_running(s)
model.reset(s)
assert s["phase"] == model.IDLE and not model.is_running(s) and not model.is_paused(s)
model.skip(s, CONFIG, at(5))
assert s["phase"] == model.IDLE, "nothing to skip while idle"

# Reconciliation on start: an endsAt hours in the past ends the block once, pending next.
s = fresh()
model.start(s, CONFIG, T0)
later = at(3 * 60)
assert model.tick(s, CONFIG, later) == model.FOCUS
assert s["completedToday"] == 1 and s["phase"] == model.SHORT_BREAK and model.is_pending(s)
assert model.tick(s, CONFIG, at(4 * 60)) is None, "the pending break does not run by itself"
assert s["completedToday"] == 1

# "+5 min" adds focus minutes but no block, and lands in the same break afterwards.
s = fresh()
s["completedToday"] = 3
model.start(s, CONFIG, T0)
model.tick(s, CONFIG, at(25))
assert s["completedToday"] == 4 and s["phase"] == model.LONG_BREAK
model.extend(s, at(25), model.FOCUS)
assert s["phase"] == model.FOCUS and model.is_running(s) and s["extension"]
assert model.remaining_seconds(s, at(25)) == 300
assert model.next_phase(s, CONFIG) == model.LONG_BREAK
assert model.tick(s, CONFIG, at(30)) == model.FOCUS
assert s["completedToday"] == 4 and s["focusMinutesToday"] == 30
assert s["phase"] == model.LONG_BREAK and model.is_pending(s)

# The agent's start command takes a custom length and refuses to replace a running phase.
s = fresh()
model.start_focus(s, CONFIG, T0, minutes=10)
assert model.remaining_seconds(s, T0) == 600
try:
    model.start_focus(s, CONFIG, at(1))
    raise AssertionError("start_focus must refuse while running")
except ValueError:
    pass
assert model.tick(s, CONFIG, at(10)) == model.FOCUS
assert s["completedToday"] == 1 and s["focusMinutesToday"] == 10

# Day rollover: a block that ended yesterday is counted, then the new day starts at zero.
s = fresh()
s["completedToday"], s["focusMinutesToday"] = 5, 125
model.start(s, CONFIG, T0)
next_day = at(18 * 60)
assert model.day_key(next_day) != model.day_key(T0)
assert model.tick(s, CONFIG, next_day) == model.FOCUS
assert s["dayKey"] == model.day_key(next_day)
assert s["completedToday"] == 0 and s["focusMinutesToday"] == 0
assert s["phase"] == model.SHORT_BREAK and model.is_pending(s), "the phase itself survives the day change"
assert s["label"] == ""

# A changed setting reaches a pending phase, not a running one.
s = fresh()
model.start(s, CONFIG, T0)
model.tick(s, CONFIG, at(25))
longer = {**CONFIG, "shortBreak": 8}
model.apply_config(s, longer)
assert s["pausedRemainingSeconds"] == 480 and s["phaseSeconds"] == 480
model.start(s, longer, at(26))
model.apply_config(s, {**CONFIG, "shortBreak": 2})
assert model.remaining_seconds(s, at(26)) == 480

# The status report is JSON-ready.
report = model.status(s, at(27))
assert report["phase"] == model.SHORT_BREAK and report["running"] is True
assert report["remainingSeconds"] == 420 and report["endsAt"].endswith("+00:00")

print("ok")
