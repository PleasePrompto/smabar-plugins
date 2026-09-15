"""Markup for Next Meeting: semantic HTML on the smabar UI kit, no SDK.

Every function returns a string the plugin pushes with app.render. Times are
formatted here from the agenda's ISO strings; the tile's countdown is ticked by
the shell (data-sb-countdown), so the tile is rendered once per state.
"""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from html import escape

import agenda

Translator = Callable[[str], str]
README = "https://github.com/PleasePrompto/smabar-plugins/tree/main/plugins/next-meeting#where-to-find-the-ics-address"
DAY_KEYS = (
    "meeting.day.mon",
    "meeting.day.tue",
    "meeting.day.wed",
    "meeting.day.thu",
    "meeting.day.fri",
    "meeting.day.sat",
    "meeting.day.sun",
)
# The tile glyph (a calendar with a clock), the same drawing as icon.svg; sized like the kit's tile icons.
GLYPH = (
    '<svg viewBox="0 0 24 24" width="1.4em" height="1.4em" fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/>'
    '<path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/></svg>'
)
GROUP_KEYS = {"now": "meeting.now", "today": "meeting.today", "tomorrow": "meeting.tomorrow", "later": "meeting.later"}


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders, HTML-escaped: tr(t, "meeting.updated", time="10:42")."""
    text = escape(t(key))
    for name, value in values.items():
        text = text.replace("{" + name + "}", escape(str(value)))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def action(name: str, label: str, value: object = "", *, symbol: str = "", icon_only: bool = False) -> str:
    """A data-action button; icon-only buttons carry aria-label AND title."""
    encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    classes = "sb-btn sb-btn-ghost sb-btn-icon" if icon_only else "sb-btn sb-btn-ghost"
    accessible = f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"' if icon_only else ""
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(encoded, quote=True)}"{accessible}>{content}</button>'
    )


def clock(event: dict, key: str) -> str:
    return agenda.at(event[key], False).strftime("%H:%M")


def day_name(event: dict, t: Translator) -> str:
    return t(DAY_KEYS[agenda.at(event["start"], event["allDay"]).weekday()])


def time_range(event: dict, t: Translator) -> str:
    if event["allDay"]:
        return t("meeting.allDay")
    return f"{clock(event, 'start')}–{clock(event, 'end')}"


def title_of(event: dict, t: Translator) -> str:
    return event["title"] or t("meeting.untitled")


def when(event: dict, group: str, t: Translator) -> str:
    """One short label per group for the hover: 'until 09:30', '14:00', 'Tomorrow 09:15', 'Mon · All day'."""
    if group == "now":
        return tr(t, "meeting.until", time=clock(event, "end"))
    moment = escape(t("meeting.allDay") if event["allDay"] else clock(event, "start"))
    if group == "today":
        return moment
    prefix = escape(t("meeting.tomorrow") if group == "tomorrow" else day_name(event, t))
    return f"{prefix} {moment}"


def countdown(event: dict, now: datetime, t: Translator) -> str:
    """'in 12 min' or 'in 1 h 05 min', ticked by the shell; the markup only changes when the hour flips."""
    parts = {name: f'<span data-sb-countdown-part="{name}"></span>' for name in ("hours", "minutes")}
    if agenda.at(event["start"], False) - now >= timedelta(hours=1):
        text = escape(t("meeting.inHours")).replace("{h}", parts["hours"]).replace("{m}", parts["minutes"])
    else:
        text = escape(t("meeting.inMinutes")).replace("{m}", parts["minutes"])
    return f'<span data-sb-countdown="{escape(event["start"], quote=True)}">{text}</span>'


# --- tile ----------------------------------------------------------------


def tile(head: dict | None, group: str, now: datetime, configured: bool, t: Translator) -> str:
    """One calm line: title · countdown, title · until end, or a muted state."""
    if not configured:
        return tile_line(f'<span class="sb-muted">{escape(t("meeting.addCalendar"))}</span>', t("meeting.addCalendar"))
    if head is None:
        return tile_line(f'<span class="sb-muted">{escape(t("meeting.free"))}</span>', t("meeting.free"))
    name = title_of(head, t)
    if head["allDay"]:
        status = f'<span class="sb-muted">{escape(t("meeting.allDay"))}</span>'
    elif group == "now":
        status = f'<span class="sb-accent">{tr(t, "meeting.until", time=clock(head, "end"))}</span>'
    else:
        status = f'<span class="sb-accent">{countdown(head, now, t)}</span>'
    body = f'<span data-marquee style="max-width: 9rem">{escape(name)}</span><span class="sb-faint">·</span>{status}'
    return tile_line(body, f"{name} · {time_range(head, t)}")


def tile_line(body: str, title: str) -> str:
    """Glyph, then the text: the same one-line shape in every state."""
    return (
        f'<div class="sb-tile" title="{escape(title, quote=True)}"><span class="sb-inline">{GLYPH}{body}</span></div>'
    )


# --- hover ---------------------------------------------------------------


def hover(groups: dict[str, list[dict]], configured: bool, t: Translator) -> str:
    """The next two events, one line each."""
    ahead = [(event, group) for group in ("now", "today", "tomorrow", "later") for event in groups[group]][:2]
    if not ahead:
        return f'<p class="sb-muted">{escape(t("meeting.free" if configured else "meeting.addCalendar"))}</p>'
    rows = "".join(
        f'<div class="sb-row"><span class="sb-mono">{when(event, group, t)}</span>'
        f'<span class="sb-wrap">{escape(title_of(event, t))}</span></div>'
        for event, group in ahead
    )
    return f'<div class="sb-list">{rows}</div>'


# --- flyout --------------------------------------------------------------


def header(updated: str, busy: bool, calendars: int, t: Translator) -> str:
    """Title, refresh button and, once a calendar is configured, the fetch state."""
    meta = ""
    if calendars:
        if busy:
            meta = escape(t("meeting.fetching"))
        elif updated:
            meta = tr(t, "meeting.updated", time=updated)
        else:
            meta = escape(t("meeting.neverFetched"))
        count = escape(t("meeting.calendarOne")) if calendars == 1 else tr(t, "meeting.calendars", n=calendars)
        meta = f'<p class="sb-meta">{meta} · {count}</p>'
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("calendar-days")}</span>'
        f'<div><h2 class="sb-title">{escape(t("meeting.title"))}</h2>{meta}</div>'
        f'<div class="sb-header-actions">{action("refresh", t("meeting.refresh"), symbol="refresh-cw", icon_only=True)}</div></div>'
    )


def warning(index: int, error: str, t: Translator) -> str:
    return (
        f'<div class="sb-alert sb-alert--warn" role="alert"><span class="sb-alert__icon">{icon("triangle-alert")}</span>'
        f'<div class="sb-alert__text">{tr(t, "meeting.calendarFailed", n=index, error=error)}</div></div>'
    )


def join_button(event: dict, primary: bool, t: Translator) -> str:
    classes = "sb-btn sb-btn--sm sb-push" + (" sb-btn-primary" if primary else "")
    return f'<a class="{classes}" href="{escape(event["joinUrl"], quote=True)}">{escape(t("meeting.join"))}</a>'


def row(event: dict, group: str, t: Translator) -> str:
    """Time column, title with a muted location line, and a Join button when there is a link."""
    moment = (
        f"{day_name(event, t)} {clock(event, 'start')}"
        if group == "later" and not event["allDay"]
        else time_range(event, t)
    )
    if group == "later" and event["allDay"]:
        moment = f"{day_name(event, t)} · {moment}"
    location = event["location"]
    sub = f'<br><small class="sb-faint">{escape(location)}</small>' if location and location != event["joinUrl"] else ""
    join = join_button(event, group == "now", t) if event["joinUrl"] else ""
    return (
        f'<div class="sb-row"><span class="sb-mono">{escape(moment)}</span>'
        f'<span class="sb-wrap">{escape(title_of(event, t))}{sub}</span>{join}</div>'
    )


def empty_calendars(t: Translator) -> str:
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon sb-accent">{icon("calendar")}</div>'
        f'<p class="sb-empty__title">{escape(t("meeting.emptyTitle"))}</p>'
        f'<p class="sb-empty__text">{escape(t("meeting.emptyHint"))} '
        f'<a href="{README}">{escape(t("meeting.howTo"))}</a></p></div>'
    )


def empty_agenda(days: int, t: Translator) -> str:
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon sb-accent">{icon("circle-check")}</div>'
        f'<p class="sb-empty__title">{escape(t("meeting.nothingTitle"))}</p>'
        f'<p class="sb-empty__text">{tr(t, "meeting.nothingHint", days=days)}</p></div>'
    )


def flyout(
    groups: dict[str, list[dict]],
    warnings: list[tuple[int, str]],
    *,
    updated: str,
    busy: bool,
    calendars: int,
    days: int,
    t: Translator,
) -> str:
    html = header(updated, busy, calendars, t)
    html += "".join(warning(index, error, t) for index, error in warnings)
    if not calendars:
        return html + empty_calendars(t)
    if not any(groups.values()):
        return html + empty_agenda(days, t)
    for group, key in GROUP_KEYS.items():
        if groups[group]:
            rows = "".join(row(event, group, t) for event in groups[group])
            html += f'<div class="sb-section">{escape(t(key))}</div><div class="sb-list">{rows}</div>'
    return html


# --- popups --------------------------------------------------------------


def reminder(event: dict, popup_id: str, t: Translator) -> str:
    """The reminder toast: title, time, Join and Dismiss."""
    detail = time_range(event, t)
    if event["location"] and event["location"] != event["joinUrl"]:
        detail += f" · {event['location']}"
    join = (
        f'<a class="sb-btn sb-btn-primary" href="{escape(event["joinUrl"], quote=True)}">{escape(t("meeting.join"))}</a>'
        if event["joinUrl"]
        else ""
    )
    return (
        f'<div class="sb-inline sb-meta">{icon("bell")}<span>{escape(t("meeting.reminder"))}</span></div>'
        f'<h2 class="sb-title sb-wrap">{escape(title_of(event, t))}</h2>'
        f'<p class="sb-meta">{escape(detail)}</p>'
        f'<div class="sb-cluster">{join}{action("dismiss", t("meeting.dismiss"), popup_id)}</div>'
    )


def failure(index: int, error: str, t: Translator) -> str:
    """Shown once when a calendar that used to work stops refreshing."""
    return (
        f'<div class="sb-inline sb-meta">{icon("triangle-alert")}<span>{escape(t("meeting.title"))}</span></div>'
        f'<p class="sb-wrap">{escape(t("meeting.fetchFailedTitle"))}: {tr(t, "meeting.calendarFailed", n=index, error=error)}</p>'
    )
