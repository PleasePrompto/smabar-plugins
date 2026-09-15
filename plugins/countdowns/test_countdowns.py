# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the countdown day math and the markup. Run: python3 test_countdowns.py"""

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import model  # noqa: E402
import views  # noqa: E402


def ev(event_id: str, day: str, *, clock: str = "", yearly: bool = False) -> dict:
    return model.make_event(event_id, f"Event {event_id}", day, clock, yearly)


TODAY = date(2026, 9, 15)

# Days left are calendar days, so a DST switch (Europe: 2026-03-29 and 2026-10-25) costs nothing.
assert model.describe([ev("a", "2026-03-30")], date(2026, 3, 28), 3)[0]["days"] == 2
assert model.describe([ev("a", "2026-10-26")], date(2026, 10, 24), 3)[0]["days"] == 2

# Yearly events roll forward to the next anniversary once passed; the day itself is today.
assert model.occurrence(date(1990, 4, 12), True, TODAY) == date(2027, 4, 12)
assert model.occurrence(date(1990, 11, 3), True, TODAY) == date(2026, 11, 3)
assert model.occurrence(date(1990, 9, 15), True, TODAY) == TODAY
assert model.occurrence(date(2026, 4, 12), False, TODAY) == date(2026, 4, 12)

# Feb 29 lands on Feb 28 in a common year and returns to Feb 29 in a leap year.
assert model.occurrence(date(2024, 2, 29), True, date(2026, 1, 1)) == date(2026, 2, 28)
assert model.occurrence(date(2024, 2, 29), True, date(2026, 2, 28)) == date(2026, 2, 28)
assert model.occurrence(date(2024, 2, 29), True, date(2026, 3, 1)) == date(2027, 2, 28)
assert model.occurrence(date(2024, 2, 29), True, date(2028, 1, 1)) == date(2028, 2, 29)

# Today, passed within keepPastDays, and gone beyond it.
entries = model.describe(
    [ev("gone", "2026-09-11"), ev("past", "2026-09-12"), ev("today", "2026-09-15")], TODAY, 3
)
assert [e["id"] for e in entries] == ["today", "past"], entries
assert entries[0]["days"] == 0 and entries[0]["status"] == "today"
assert entries[1]["days"] == -3 and entries[1]["status"] == "past"
assert model.describe([ev("past", "2026-09-12")], TODAY, 2) == []
kept = model.prune([ev("gone", "2026-09-11"), ev("keep", "2026-09-13"), ev("bday", "1990-01-01", yearly=True)], TODAY, 3)
assert [e["id"] for e in kept] == ["keep", "bday"], kept

# Sort order: soonest first, all-day before timed on the same day, ties by title,
# passed events last with the most recent first.
mixed = [
    ev("far", "2026-12-24"),
    ev("timed", "2026-09-27", clock="09:00"),
    ev("allday", "2026-09-27"),
    ev("older", "2026-09-13"),
    ev("recent", "2026-09-14"),
    ev("now", "2026-09-15"),
    ev("week", "2026-09-20"),
]
described = model.describe(mixed, TODAY, 3)
order = [e["id"] for e in described]
assert order == ["now", "week", "allday", "timed", "far", "recent", "older"], order
tie = [model.make_event("b", "beta", "2026-10-01", "", False), model.make_event("a", "Alpha", "2026-10-01", "", False)]
assert [e["id"] for e in model.describe(tie, TODAY, 3)] == ["a", "b"]

# The live countdown only applies to a timed event less than a day away and still ahead.
soon = model.describe([ev("x", "2026-09-16", clock="09:00")], TODAY, 3)[0]
assert soon["days"] == 1
assert model.live_countdown(soon, datetime(2026, 9, 15, 20, 0)) == "2026-09-16T09:00"
assert model.live_countdown(soon, datetime(2026, 9, 15, 8, 0)) == ""
gone_by = model.describe([ev("y", "2026-09-15", clock="08:00")], TODAY, 3)[0]
assert gone_by["days"] == 0 and model.live_countdown(gone_by, datetime(2026, 9, 15, 9, 0)) == ""
assert model.live_countdown(model.describe([ev("z", "2026-09-16")], TODAY, 3)[0], datetime(2026, 9, 15, 20, 0)) == ""

# Across the spring DST switch the live threshold follows real elapsed time, not wall-clock hours.
if hasattr(time, "tzset"):
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    dst = model.describe([ev("dst", "2026-03-29", clock="12:00")], date(2026, 3, 28), 3)[0]
    assert model.live_countdown(dst, datetime(2026, 3, 28, 11, 30)) == "2026-03-29T12:00"
    assert model.live_countdown(dst, datetime(2026, 3, 28, 10, 30)) == ""

# Validation names the field it rejects.
assert model.parse_time("09:00:30") == "09:00" and model.parse_time("") == "" and model.parse_time(None) == ""
for field, args in [
    ("title", ("", "2026-01-01", "", False)),
    ("title", ("x" * 81, "2026-01-01", "", False)),
    ("date", ("t", "2026-02-30", "", False)),
    ("date", ("t", "01.02.2026", "", False)),
    ("time", ("t", "2026-01-01", "9:00", False)),
    ("repeatYearly", ("t", "2026-01-01", "", "yes")),
]:
    try:
        model.make_event("id", *args)
    except model.InvalidEvent as exc:
        assert exc.field == field, (field, exc.field)
    else:
        raise AssertionError(f"accepted {args}")
assert model.make_event("id", "  Two   words ", "2026-01-01", None, True)["title"] == "Two words"

# Markup: every state keeps the tile's shape, the live count uses the shell hook,
# and every string comes from the locale.
en = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
de = json.loads((HERE / "locales" / "de.json").read_text(encoding="utf-8"))
assert set(en) == set(de), set(en) ^ set(de)
t = en.__getitem__
assert "No countdowns" in views.tile(None, "", t) and 'class="sb-tile"' in views.tile(None, "", t)
assert "5 d" in views.tile(described[1], "", t) and "data-marquee" in views.tile(described[1], "", t)
live_tile = views.tile(soon, "2026-09-16T09:00", t)
assert 'data-sb-countdown="2026-09-16T09:00"' in live_tile and 'data-sb-countdown-part="hours"' in live_tile
assert "today!" in views.tile(entries[0], "", t)
fly = views.flyout(described, 10, "new0", "", t)
assert fly.count("<dialog") == 7 and "more" not in fly and "sb-warn" in fly and "2 d ago" in fly and "1 d ago" in fly
assert 'data-action="save:allday"' in fly and 'aria-label="Delete"' in fly and 'title="Edit"' in fly
assert "Sun, 27 Sep 2026 · 09:00" in fly and "7 upcoming" not in fly and "5 upcoming" in fly
short = views.flyout(described, 4, "new0", "", t)
assert short.count("<dialog") == 4 and "+3 more" in short
assert "So, 27. Sep 2026" in views.flyout(described, 4, "new0", "", de.__getitem__)
empty = views.flyout([], 8, "new1", "", t)
assert "<details" in empty and " open" in empty and "Nothing to count down to" in empty and "<dialog" not in empty
assert "Not saved" in views.flyout([], 8, "new1", "Pick a valid date.", t)
assert "Today: Event today" in views.popup(entries[0], t) and 'data-action="dismiss"' in views.popup(entries[0], t)
assert views.hover([], t).count("sb-row") == 1 and views.hover(described[:3], t).count("sb-row") == 3

# The tile carries its own icon in every state (the manifest declares none).
for html in (views.tile(None, "", t), views.tile(described[1], "", t), live_tile):
    assert html.startswith('<div class="sb-tile"') and html.count('data-lucide="calendar-days"') == 1, html

print("ok")
