"""Markup for Countdowns on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing
here touches the SDK, so this module renders and tests without a running bar.
"""

from collections.abc import Callable
from datetime import date
from html import escape

Translator = Callable[[str], str]

WARN_DAYS = 7
TILE_ICON = "calendar-days"


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "countdowns.days", n=3)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def icon_button(name: str, label: str, *, symbol: str, value: str = "", dialog: str = "") -> str:
    """A ghost icon-only button with aria-label AND title, so the control has a name.

    With `dialog` it opens that <dialog> through the native command invoker;
    otherwise it is a data-action with `value` as its payload."""
    named = f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"'
    trigger = (
        f' commandfor="{escape(dialog, quote=True)}" command="show-modal"'
        if dialog
        else f' data-action="{escape(name)}" data-value="{escape(value, quote=True)}"'
    )
    return f'<button type="button" class="sb-btn sb-btn-ghost sb-btn-icon"{trigger}{named}>{icon(symbol)}</button>'


def format_date(day: date, t: Translator) -> str:
    weekdays = t("countdowns.weekdays").split()
    months = t("countdowns.months").split()
    return tr(
        t,
        "countdowns.dateFormat",
        weekday=weekdays[day.weekday()],
        day=day.day,
        month=months[day.month - 1],
        year=day.year,
    )


def count_text(days: int, t: Translator) -> str:
    if days == 0:
        return t("countdowns.today")
    if days < 0:
        return tr(t, "countdowns.ago", n=-days)
    return tr(t, "countdowns.days", n=days)


def count_class(days: int) -> str:
    if days == 0:
        return "sb-accent"
    if days < 0:
        return "sb-muted"
    return "sb-warn" if days < WARN_DAYS else ""


def part(unit: str) -> str:
    return f'<span data-sb-countdown-part="{unit}"></span>'


def tile(entry: dict | None, live_iso: str, t: Translator) -> str:
    """Basic cover: the icon, the next title and its day count, in every state.

    `live_iso` switches the count to the shell's ticking hours/minutes when a
    timed event is less than a day away."""
    if entry is None:
        return f'<div class="sb-tile">{icon(TILE_ICON)}<span class="sb-muted">{escape(t("countdowns.empty"))}</span></div>'
    if live_iso:
        text = escape(t("countdowns.live")).replace("{h}", part("hours")).replace("{m}", part("minutes"))
        value = f'<span class="sb-accent" data-sb-countdown="{escape(live_iso, quote=True)}">{text}</span>'
    else:
        value = f'<span class="sb-accent">{escape(count_text(entry["days"], t))}</span>'
    when = format_date(date.fromisoformat(entry["when"]), t)
    tooltip = escape(f"{entry['title']} · {when}", quote=True)
    return (
        f'<div class="sb-tile" title="{tooltip}">{icon(TILE_ICON)}'
        f'<span data-marquee style="max-width: 9rem">{escape(entry["title"])}</span>'
        f'<span class="sb-muted">·</span>{value}</div>'
    )


def hover(entries: list[dict], t: Translator) -> str:
    """The hover preview: the next few events, one line each, no controls."""
    if not entries:
        return f'<div class="sb-row"><span class="sb-muted">{escape(t("countdowns.empty"))}</span></div>'
    rows = "".join(
        f'<div class="sb-row"><span class="sb-wrap">{escape(entry["title"])}</span>'
        f'<span class="sb-push {count_class(entry["days"])}">{escape(count_text(entry["days"], t))}</span></div>'
        for entry in entries
    )
    return f'<div class="sb-list">{rows}</div>'


def fields(key: str, t: Translator, event: dict | None = None) -> str:
    """Title, date, optional time and the yearly switch; field names carry `key`
    so the add form and every edit dialog stay distinct in one surface."""
    title = escape(event["title"], quote=True) if event else ""
    day = event["date"] if event else ""
    clock = event["time"] if event else ""
    checked = " checked" if event and event["repeatYearly"] else ""
    return (
        f'<div class="sb-field-stack"><label class="sb-field__label" for="title-{key}">{escape(t("countdowns.titleLabel"))}</label>'
        f'<input id="title-{key}" class="sb-input" data-field="title-{key}" type="text" required maxlength="80" value="{title}"'
        f' placeholder="{escape(t("countdowns.titlePlaceholder"), quote=True)}" aria-describedby="title-{key}-error">'
        f'<p class="sb-field__error" id="title-{key}-error">{escape(t("countdowns.titleRequired"))}</p></div>'
        f'<div class="sb-field-stack"><label class="sb-field__label" for="date-{key}">{escape(t("countdowns.dateLabel"))}</label>'
        f'<input id="date-{key}" class="sb-input" data-field="date-{key}" data-sb-temporal type="date" required value="{day}"'
        f' aria-describedby="date-{key}-hint">'
        f'<p class="sb-field__hint" id="date-{key}-hint">{escape(t("countdowns.dateHint"))}</p></div>'
        f'<div class="sb-field-stack"><label class="sb-field__label" for="time-{key}">{escape(t("countdowns.timeLabel"))}'
        f' <span class="sb-meta">· {escape(t("countdowns.optional"))}</span></label>'
        f'<input id="time-{key}" class="sb-input" data-field="time-{key}" data-sb-temporal type="time" value="{clock}"'
        f' aria-describedby="time-{key}-hint">'
        f'<p class="sb-field__hint" id="time-{key}-hint">{escape(t("countdowns.timeHint"))}</p></div>'
        f'<label class="sb-switch"><input type="checkbox" role="switch" data-field="yearly-{key}"{checked}> {escape(t("countdowns.yearly"))}</label>'
    )


def add_form(form_key: str, expanded: bool, t: Translator) -> str:
    return (
        f'<details class="sb-accordion-item"{" open" if expanded else ""}>'
        f'<summary>{escape(t("countdowns.addSection"))}</summary><div class="sb-accordion-item__body">'
        f'<form class="sb-stack">{fields(form_key, t)}'
        f'<div class="sb-cluster"><button type="submit" class="sb-btn sb-btn-primary" data-action="add">'
        f'{icon("plus")}{escape(t("countdowns.addButton"))}</button></div></form></div></details>'
    )


def row(entry: dict, t: Translator) -> str:
    when = format_date(date.fromisoformat(entry["when"]), t)
    details = [when]
    if entry["time"]:
        details.append(entry["time"])
    if entry["repeatYearly"]:
        details.append(t("countdowns.yearlyShort"))
    muted = " sb-muted" if entry["days"] < 0 else ""
    return (
        f'<div class="sb-row{muted}"><div class="sb-wrap"><div>{escape(entry["title"])}</div>'
        f'<div class="sb-text-xs sb-muted">{escape(" · ".join(details))}</div></div>'
        f'<strong class="sb-push {count_class(entry["days"])}">{escape(count_text(entry["days"], t))}</strong>'
        f'{icon_button("edit", t("countdowns.edit"), symbol="pencil", dialog="edit-" + entry["id"])}'
        f'{icon_button("remove", t("countdowns.remove"), symbol="trash-2", value=entry["id"])}</div>'
    )


def edit_dialog(entry: dict, t: Translator) -> str:
    dialog = f"edit-{entry['id']}"
    return (
        f'<dialog class="sb-modal sb-modal--sm" id="{dialog}" aria-labelledby="{dialog}-title">'
        f'<div class="sb-modal__header"><h3 class="sb-modal__title" id="{dialog}-title">{escape(t("countdowns.editTitle"))}</h3></div>'
        f'<div class="sb-modal__body"><div class="sb-stack">{fields(entry["id"], t, entry)}</div></div>'
        f'<div class="sb-modal__footer">'
        f'<button type="button" class="sb-btn sb-btn-ghost" commandfor="{dialog}" command="close">{escape(t("countdowns.cancel"))}</button>'
        f'<button type="button" class="sb-btn sb-btn-primary" commandfor="{dialog}" command="close" data-action="save:{entry["id"]}">'
        f'{escape(t("countdowns.save"))}</button></div></dialog>'
    )


def flyout(entries: list[dict], max_items: int, form_key: str, error: str, t: Translator) -> str:
    """Header, an optional error, the collapsed add form, the list and its edit dialogs."""
    upcoming = sum(1 for entry in entries if entry["days"] >= 0)
    shown = entries[:max_items]
    parts = [
        f'<div class="sb-header"><span class="sb-icon-badge">{icon(TILE_ICON)}</span>'
        f'<div><h2 class="sb-title">{escape(t("countdowns.title"))}</h2>'
        f'<p class="sb-meta">{escape(tr(t, "countdowns.upcoming", n=upcoming))}</p></div></div>'
    ]
    if error:
        parts.append(
            f'<div class="sb-alert sb-alert--danger" role="alert"><span class="sb-alert__icon" aria-hidden="true">{icon("circle-alert")}</span>'
            f'<div><div class="sb-alert__title">{escape(t("countdowns.errorTitle"))}</div>'
            f'<div class="sb-alert__text">{escape(error)}</div></div></div>'
        )
    parts.append(add_form(form_key, bool(error) or not entries, t))
    if not entries:
        parts.append(
            f'<div class="sb-empty"><div class="sb-empty__icon" aria-hidden="true">{icon("calendar")}</div>'
            f'<p class="sb-empty__title">{escape(t("countdowns.emptyTitle"))}</p>'
            f'<p class="sb-empty__text">{escape(t("countdowns.emptyText"))}</p></div>'
        )
    else:
        parts.append('<div class="sb-list">' + "".join(row(entry, t) for entry in shown) + "</div>")
        if len(entries) > len(shown):
            parts.append(f'<p class="sb-meta">{escape(tr(t, "countdowns.more", n=len(entries) - len(shown)))}</p>')
        parts.extend(edit_dialog(entry, t) for entry in shown)
    return "".join(parts)


def popup(entry: dict, t: Translator) -> str:
    """The on-the-day toast; its Dismiss button is an ordinary data-action."""
    return (
        f'<div class="sb-row">{icon(TILE_ICON)}'
        f'<span class="sb-wrap">{escape(tr(t, "countdowns.todayPopup", title=entry["title"]))}</span>'
        f'<button type="button" class="sb-btn sb-btn-ghost sb-push" data-action="dismiss"'
        f' data-value="{escape(entry["id"], quote=True)}">{escape(t("countdowns.dismiss"))}</button></div>'
    )
