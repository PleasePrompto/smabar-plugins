# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the platform selection, the session timer and the markup.
Run: python3 test_backend.py. No inhibitor is started and no bar is needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import views  # noqa: E402
from backend import (  # noqa: E402
    BackendError,
    LinuxBackend,
    MacBackend,
    WindowsBackend,
    choose_backend,
    end_at,
    ended,
    plan_linux,
    remaining_minutes,
)

HELPER = Path("inhibit_linux.py")


def which_from(names: set[str]):
    return lambda name, path=None: f"/usr/bin/{name}" if name in names else None


def quiet(message: str) -> None:
    pass


# Platform selection never starts anything.
assert isinstance(choose_backend("Windows", which_from(set()), "", HELPER, quiet), WindowsBackend)
assert isinstance(choose_backend("Darwin", which_from({"caffeinate"}), "", HELPER, quiet), MacBackend)
assert isinstance(choose_backend("Linux", which_from(set()), ":0", HELPER, quiet), LinuxBackend)

# Linux: systemd covers sleep; the idle inhibitors are tried in this order.
gnome = plan_linux(
    which_from({"systemd-inhibit", "gnome-session-inhibit", "python3", "xdg-screensaver"}), ":0"
)
assert gnome.sleep and gnome.idle == (
    "gnome-session-inhibit",
    "org.freedesktop.ScreenSaver",
    "xdg-screensaver",
), gnome
cinnamon = plan_linux(which_from({"systemd-inhibit", "python3", "xdg-screensaver"}), ":0")
assert cinnamon.idle == ("org.freedesktop.ScreenSaver", "xdg-screensaver"), cinnamon
# xdg-screensaver is X11 only: without DISPLAY it is not a candidate.
wayland = plan_linux(which_from({"systemd-inhibit", "xdg-screensaver"}), "")
assert wayland == (True, ()), wayland
bare = plan_linux(which_from(set()), ":0")
assert bare == (False, ()), bare

# No tool at all is an error the user can read, never a silent no-op.
try:
    LinuxBackend(bare, HELPER, which_from(set()), quiet).start()
    raise AssertionError("expected BackendError")
except BackendError as exc:
    assert "no inhibitor found" in str(exc), exc
try:
    MacBackend(which_from(set())).start()
    raise AssertionError("expected BackendError")
except BackendError as exc:
    assert "caffeinate" in str(exc), exc

# Timer bookkeeping: 0 minutes is untimed, partial minutes round up, never down.
now = 1_000_000.0
assert end_at(now, 0) is None
assert end_at(now, 30) == now + 1800
assert remaining_minutes(None, now) is None
assert remaining_minutes(now + 1800, now) == 30
assert remaining_minutes(now + 1801, now) == 31
assert remaining_minutes(now + 1, now) == 1
assert remaining_minutes(now - 5, now) == 0
assert not ended(None, now + 10**9)
assert not ended(now + 1, now)
assert ended(now, now)
assert ended(now - 1, now)

# Markup: every state keeps the tile's shape; a timed session counts down in
# the shell instead of re-rendering; the switch always names its target state.
labels = {
    "awake.minutes": "{n} min",
    "awake.hours": "{n} h",
    "awake.untilOff": "Until off",
    "awake.hoverOn": "Keep Awake · on for {minutes} more min",
}
t = lambda key: labels.get(key, key)  # noqa: E731
off = {"on": False, "busy": False, "minutes": 0, "end_at": None, "mechanism": "", "error": ""}
timed = {**off, "on": True, "minutes": 60, "end_at": now + 3600, "mechanism": "systemd-inhibit"}
untimed = {**timed, "minutes": 0, "end_at": None}
for snapshot in (off, timed, untimed, {**off, "busy": True}):
    assert views.tile(snapshot, t).startswith('<div class="sb-tile"><svg '), snapshot
assert "sb-muted" in views.tile(off, t) and "sb-accent" in views.tile(timed, t)
assert "data-sb-countdown=" in views.tile(timed, t)
assert "data-sb-countdown" not in views.tile(untimed, t)
assert 'data-value="on"' in views.flyout(off, t) and " checked" not in views.flyout(off, t)
assert 'data-value="off"' in views.flyout(timed, t) and " checked" in views.flyout(timed, t)
assert views.flyout(timed, t).count("is-selected") == 1
assert views.flyout(off, t).count("is-selected") == 0
assert "sb-hero" in views.flyout(timed, t) and "sb-hero" not in views.flyout(off, t)
assert "sb-alert--danger" in views.flyout({**off, "error": "no bus"}, t)
assert "no bus" in views.flyout({**off, "error": "no bus"}, t)
assert "{minutes}" not in views.hover(timed, 42, t)
assert "42" in views.hover(timed, 42, t)
assert views.duration_label(30, t) == "30 min"
assert views.duration_label(120, t) == "2 h"
assert views.duration_label(0, t) == "Until off"

print("ok")
