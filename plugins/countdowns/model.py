"""Countdown day math on plain dates. No bar imports, so test_countdowns.py runs anywhere.

Days left are calendar days: `event day - today` on `date` objects, which never
see clocks or DST. A yearly event targets its next anniversary on or after today.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$")
TITLE_MAX = 80
DAY_SECONDS = 86400


class InvalidEvent(ValueError):
    """A rejected field; `field` names it so the UI can show a localized message."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def parse_title(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEvent("title", "title must be a non-empty string")
    title = " ".join(value.split())
    if len(title) > TITLE_MAX:
        raise InvalidEvent("title", f"title must be at most {TITLE_MAX} characters")
    return title


def parse_date(value: object) -> date:
    text = value.strip() if isinstance(value, str) else ""
    if not DATE_RE.match(text):
        raise InvalidEvent("date", "date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidEvent("date", f"date is not a calendar day: {text}") from exc


def parse_time(value: object) -> str:
    """'HH:MM' (seconds tolerated and dropped); None or '' means no time."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidEvent("time", "time must be HH:MM")
    text = value.strip()
    if not text:
        return ""
    match = TIME_RE.match(text)
    if not match:
        raise InvalidEvent("time", "time must be HH:MM")
    return f"{match.group(1)}:{match.group(2)}"


def make_event(event_id: str, title: object, day: object, clock: object, yearly: object) -> dict:
    """A validated event record; raises InvalidEvent naming the bad field."""
    if not isinstance(yearly, bool):
        raise InvalidEvent("repeatYearly", "repeatYearly must be true or false")
    return {
        "id": event_id,
        "title": parse_title(title),
        "date": parse_date(day).isoformat(),
        "time": parse_time(clock),
        "repeatYearly": yearly,
        "notifiedFor": "",
    }


def anniversary(day: date, year: int) -> date:
    """The event's day in `year`."""
    # ponytail: Feb 29 lands on Feb 28 in a common year — one rule, no setting.
    last = calendar.monthrange(year, day.month)[1]
    return date(year, day.month, min(day.day, last))


def occurrence(day: date, yearly: bool, today: date) -> date:
    """The day the countdown targets: the event itself, or for a yearly event the
    next anniversary on or after today (the day itself still counts as today)."""
    if not yearly:
        return day
    this_year = anniversary(day, today.year)
    return this_year if this_year >= today else anniversary(day, today.year + 1)


def status(days: int) -> str:
    if days == 0:
        return "today"
    return "upcoming" if days > 0 else "past"


def describe(events: list[dict], today: date, keep_past_days: int) -> list[dict]:
    """The visible events, each with `when` (ISO target day), `days` (calendar days
    left, negative once passed) and `status`; sorted soonest first, the same day
    all-day before timed, and passed events last with the most recent first."""
    entries = []
    for event in events:
        when = occurrence(date.fromisoformat(event["date"]), event["repeatYearly"], today)
        days = (when - today).days
        if days < -keep_past_days:
            continue
        entries.append({**event, "when": when.isoformat(), "days": days, "status": status(days)})
    entries.sort(key=lambda e: (e["days"] < 0, abs(e["days"]), e["time"], e["title"].casefold()))
    return entries


def prune(events: list[dict], today: date, keep_past_days: int) -> list[dict]:
    """The events that are still visible; one-time events older than keep_past_days drop out."""
    visible = {entry["id"] for entry in describe(events, today, keep_past_days)}
    return [event for event in events if event["id"] in visible]


def live_countdown(entry: dict, now: datetime) -> str:
    """The local ISO minute the shell should count down to while a timed event is
    less than a day away, else ''. `now` may be naive (local) or aware."""
    if not entry["time"] or not 0 <= entry["days"] <= 1:
        return ""
    target = datetime.combine(date.fromisoformat(entry["when"]), time.fromisoformat(entry["time"]))
    left = (target.astimezone() - now.astimezone()).total_seconds()
    return target.isoformat(timespec="minutes") if 0 < left < DAY_SECONDS else ""
