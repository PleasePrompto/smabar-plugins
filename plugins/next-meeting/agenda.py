"""ICS parsing and agenda selection, no bar needed.

parse_ics turns calendar text into a flat list of occurrences in local time
(recurrences expanded, EXDATE and RECURRENCE-ID honoured). The other functions
pick what each surface shows: what is still ahead, the Now / Today / Tomorrow /
Later groups, and the one event the tile headlines.

Event shape (JSON-friendly, cached as is):
{uid, title, start, end, allDay, location, joinUrl}; start/end are ISO strings
with the local offset, or plain dates for all-day events (end exclusive, as in
the ICS). The plugin adds calendarIndex.
"""

from datetime import date, datetime, time, timedelta

import icalendar
import recurring_ical_events

import links

# Where a join link may hide, in the order they are trusted.
LINK_FIELDS = (
    "URL",
    "X-GOOGLE-CONFERENCE",
    "CONFERENCE",
    "X-MICROSOFT-SKYPETEAMSMEETINGURL",
    "LOCATION",
    "DESCRIPTION",
)


def text(component: icalendar.Component, name: str) -> str:
    value = component.get(name)
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def local(value: date | datetime) -> str:
    """ISO string in local time; a date stays a date."""
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="seconds")
    return value.isoformat()


def at(value: str, all_day: bool) -> datetime:
    """The aware local datetime behind a stored start or end."""
    moment = datetime.combine(date.fromisoformat(value), time()) if all_day else datetime.fromisoformat(value)
    return moment.astimezone()


def parse_ics(data: bytes | str, start: datetime, end: datetime) -> list[dict]:
    """Every occurrence overlapping [start, end], sorted by start.

    Raises ValueError when the text is not a calendar. A single broken series
    is skipped instead of failing the whole calendar.
    """
    events = []
    for calendar in icalendar.Calendar.from_ical(data, multiple=True):
        query = recurring_ical_events.of(calendar, skip_bad_series=True)
        for occurrence in query.between(start, end):
            begin = occurrence.start
            location = text(occurrence, "LOCATION").strip()
            events.append(
                {
                    "uid": text(occurrence, "UID"),
                    "title": text(occurrence, "SUMMARY").strip(),
                    "start": local(begin),
                    "end": local(occurrence.end),
                    "allDay": not isinstance(begin, datetime),
                    "location": location,
                    "joinUrl": links.find_join_url((text(occurrence, field) for field in LINK_FIELDS), location),
                }
            )
    events.sort(key=lambda event: (at(event["start"], event["allDay"]), event["title"]))
    return events


def upcoming(events: list[dict], now: datetime, show_all_day: bool = True) -> list[dict]:
    """Events that have not ended yet, sorted by start."""
    kept = [
        event for event in events if (show_all_day or not event["allDay"]) and at(event["end"], event["allDay"]) > now
    ]
    return sorted(kept, key=lambda event: at(event["start"], event["allDay"]))


def sections(events: list[dict], now: datetime) -> dict[str, list[dict]]:
    """Group upcoming events into now / today / tomorrow / later.

    A running timed event is "now"; an all-day event sits on its first visible
    day, so a three-day offsite shows once, not three times.
    """
    today = now.date()
    groups: dict[str, list[dict]] = {"now": [], "today": [], "tomorrow": [], "later": []}
    for event in events:
        start = at(event["start"], event["allDay"])
        if event["allDay"]:
            day = max(start.date(), today)
        elif start <= now:
            groups["now"].append(event)
            continue
        else:
            day = start.date()
        if day == today:
            groups["today"].append(event)
        elif day == today + timedelta(days=1):
            groups["tomorrow"].append(event)
        else:
            groups["later"].append(event)
    return groups


def headline(groups: dict[str, list[dict]]) -> tuple[dict | None, str]:
    """The event the tile shows and its group: the running event that ends
    first, else the next timed event today, else today's all-day event."""
    if groups["now"]:
        return min(groups["now"], key=lambda event: at(event["end"], False)), "now"
    timed = [event for event in groups["today"] if not event["allDay"]]
    ahead = timed or groups["today"]
    return (ahead[0], "today") if ahead else (None, "")
