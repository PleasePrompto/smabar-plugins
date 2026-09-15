# /// script
# requires-python = ">=3.12"
# dependencies = ["icalendar==7.3.0", "recurring-ical-events==3.8.2"]
# ///
"""Self-check for ICS expansion, agenda grouping, join links and the markup.

Run: uv run --script test_ics.py   (no bar needed; uv resolves the dependencies)
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import agenda  # noqa: E402
import links  # noqa: E402
import views  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
EN = json.loads((Path(__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
DE = json.loads((Path(__file__).parent / "locales" / "de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)
t = EN.__getitem__  # a missing key raises instead of leaking a raw key into the markup

ZOOM = "https://us02web.zoom.us/j/123456789?pwd=abc"
TEAMS = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=%7b%7d"
SAMPLE = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//smabar//next-meeting test//EN
BEGIN:VEVENT
UID:standup@example.com
DTSTART;TZID=Europe/Berlin:20260907T091500
DTEND;TZID=Europe/Berlin:20260907T093000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
EXDATE;TZID=Europe/Berlin:20260916T091500
SUMMARY:Standup
DESCRIPTION:Daily sync.\\nJoin Zoom Meeting: {ZOOM}.
END:VEVENT
BEGIN:VEVENT
UID:offsite@example.com
DTSTART;VALUE=DATE:20260916
DTEND;VALUE=DATE:20260917
SUMMARY:Offsite
LOCATION:Lakeside Lodge
END:VEVENT
BEGIN:VEVENT
UID:review@example.com
DTSTART:20260915T130000Z
DTEND:20260915T140000Z
SUMMARY:Design review
LOCATION:{TEAMS}
END:VEVENT
BEGIN:VEVENT
UID:lunch@example.com
DTSTART:20260917T120000
DTEND:20260917T130000
SUMMARY:Lunch
LOCATION:Canteen
END:VEVENT
END:VCALENDAR
"""

# --- expansion in a fixed window -------------------------------------------

window = (datetime(2026, 9, 14, tzinfo=BERLIN), datetime(2026, 9, 18, tzinfo=BERLIN))
events = agenda.parse_ics(SAMPLE, *window)
by_title = {}
for event in events:
    by_title.setdefault(event["title"], []).append(event)

# The weekly Standup expands to Mon, Tue and Thu: Wednesday is the EXDATE.
standups = [agenda.at(event["start"], False) for event in by_title["Standup"]]
assert standups == [
    datetime(2026, 9, 14, 9, 15, tzinfo=BERLIN),
    datetime(2026, 9, 15, 9, 15, tzinfo=BERLIN),
    datetime(2026, 9, 17, 9, 15, tzinfo=BERLIN),
], standups
assert all(not event["allDay"] for event in by_title["Standup"])
assert all(event["joinUrl"] == ZOOM for event in by_title["Standup"]), by_title["Standup"][0]

# The all-day event keeps its dates; the exclusive end is the next day.
(offsite,) = by_title["Offsite"]
assert offsite["allDay"] and offsite["start"] == "2026-09-16" and offsite["end"] == "2026-09-17", offsite
assert offsite["joinUrl"] == "" and offsite["location"] == "Lakeside Lodge"

# A UTC event lands in local time; the Teams link in LOCATION is the join link.
(review,) = by_title["Design review"]
assert agenda.at(review["start"], False) == datetime(2026, 9, 15, 13, 0, tzinfo=UTC), review
assert review["joinUrl"] == TEAMS and review["location"] == TEAMS

# A floating time is the machine's local time.
(lunch,) = by_title["Lunch"]
assert agenda.at(lunch["start"], False) == datetime(2026, 9, 17, 12, 0).astimezone(), lunch
assert lunch["joinUrl"] == ""

assert [event["title"] for event in events] == ["Standup", "Standup", "Design review", "Offsite", "Standup", "Lunch"], [
    event["title"] for event in events
]

# --- grouping around a fixed "now" -----------------------------------------

now = datetime(2026, 9, 15, 9, 20, tzinfo=BERLIN)  # inside Tuesday's Standup
ahead = agenda.upcoming(events, now)
assert [event["title"] for event in ahead] == ["Standup", "Design review", "Offsite", "Standup", "Lunch"]
assert [event["title"] for event in agenda.upcoming(events, now, show_all_day=False)] == [
    "Standup",
    "Design review",
    "Standup",
    "Lunch",
]
groups = agenda.sections(ahead, now)
assert [event["title"] for event in groups["now"]] == ["Standup"]
assert [event["title"] for event in groups["today"]] == ["Design review"]
assert [event["title"] for event in groups["tomorrow"]] == ["Offsite"]
assert [event["title"] for event in groups["later"]] == ["Standup", "Lunch"]

head, group = agenda.headline(groups)
assert head["title"] == "Standup" and group == "now"
later = datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN)
head, group = agenda.headline(agenda.sections(agenda.upcoming(events, later), later))
assert head["title"] == "Design review" and group == "today"
evening = datetime(2026, 9, 15, 20, 0, tzinfo=BERLIN)
assert agenda.headline(agenda.sections(agenda.upcoming(events, evening), evening)) == (None, "")
# An all-day event headlines only when no timed event is left that day.
offsite_day = datetime(2026, 9, 16, 8, 0, tzinfo=BERLIN)
head, group = agenda.headline(agenda.sections(agenda.upcoming(events, offsite_day), offsite_day))
assert head["title"] == "Offsite" and group == "today"

# --- join links ------------------------------------------------------------

assert links.find_join_url(["Room 4", f"Dial in: {ZOOM}."]) == ZOOM
assert links.find_join_url(['<a href="https://meet.google.com/abc-defg-hij?authuser=0&amp;hs=1">Meet</a>']) == (
    "https://meet.google.com/abc-defg-hij?authuser=0&hs=1"
)
assert links.find_join_url(["https://example.com/agenda"], location="https://meet.example.com/room") == (
    "https://meet.example.com/room"
)
assert links.find_join_url(["https://example.com/agenda"], location="http://example.com") == ""
assert links.find_join_url([], location="Room 4") == ""
assert links.is_meeting_url("https://acme.webex.com/meet/jane") and not links.is_meeting_url("https://notzoom.us/x")

# --- markup ----------------------------------------------------------------

tile = views.tile(None, "", now, False, t)
assert "Add a calendar" in tile and "sb-muted" in tile
assert "No more meetings today" in views.tile(None, "", now, True, t)
running = views.tile(groups["now"][0], "now", now, True, t)
assert "until 09:30" in running and "sb-accent" in running and "data-sb-countdown" not in running
soon = views.tile(groups["today"][0], "today", now, True, t)  # 15:00 local, more than an hour away
assert 'data-sb-countdown="' in soon and 'data-sb-countdown-part="hours"' in soon
minutes_only = views.tile(groups["today"][0], "today", datetime(2026, 9, 15, 14, 30, tzinfo=BERLIN), True, t)
assert 'data-sb-countdown-part="minutes"' in minutes_only and 'data-sb-countdown-part="hours"' not in minutes_only
assert "All day" in views.tile(offsite, "today", now, True, t)
# Every tile state starts with the glyph, then the text, on one line.
for markup in (tile, running, soon, minutes_only, views.tile(None, "", now, True, t)):
    assert markup.count("<svg") == 1 and markup.index("<svg") < markup.index("</svg>") < markup.index(
        "</span></div>"
    ), markup

hover = views.hover(groups, True, t)
assert hover.count("sb-row") == 2 and "until 09:30" in hover and "Design review" in hover
assert "Add a calendar" in views.hover({"now": [], "today": [], "tomorrow": [], "later": []}, False, t)

flyout = views.flyout(groups, [(2, "HTTP 403")], updated="10:42", busy=False, calendars=2, days=7, t=t)
for text in ("Now", "Today", "Tomorrow", "Later", "Updated 10:42", "2 calendars", "Calendar 2: HTTP 403", "All day"):
    assert text in flyout, text
assert flyout.count(f'href="{views.escape(ZOOM, quote=True)}"') == 2 and TEAMS.replace("&", "&amp;") in flyout
assert "Lakeside Lodge" in flyout and flyout.count(">Join<") == 3
empty = views.flyout(
    {"now": [], "today": [], "tomorrow": [], "later": []}, [], updated="", busy=False, calendars=0, days=7, t=t
)
assert "No calendar yet" in empty and views.README in empty and "sb-meta" not in empty
quiet = views.flyout(
    {"now": [], "today": [], "tomorrow": [], "later": []}, [], updated="10:42", busy=True, calendars=1, days=7, t=t
)
assert "Nothing scheduled" in quiet and "next 7 days" in quiet and "Refreshing… · 1 calendar" in quiet

popup = views.reminder(review, "rem-1", t)
assert "Design review" in popup and 'data-action="dismiss"' in popup and 'data-value="rem-1"' in popup
assert f'href="{views.escape(TEAMS, quote=True)}"' in popup and TEAMS not in popup.split("</h2>")[1].split("<div")[0]
assert "Calendar 1: HTTP 403" in views.failure(1, "HTTP 403", t)

print("ok")
