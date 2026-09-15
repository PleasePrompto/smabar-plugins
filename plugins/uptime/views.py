"""Markup for the Uptime plugin: semantic HTML on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing
here touches the SDK; rows are the dicts plugin.describe() builds, so the
same shape feeds the agent commands and the surfaces.
"""

import json
from collections.abc import Callable
from html import escape

Translator = Callable[[str], str]
NO_DATA = "–"
HOVER_ROWS = 5
MARKS = {
    "up": ("circle-check", "sb-ok", "uptime.state.up"),
    "down": ("circle-x", "sb-crit", "uptime.state.down"),
    "unknown": ("circle", "sb-muted", "uptime.state.unknown"),
}


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "uptime.tile.up", ok=3, total=4)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def action(
    name: str,
    label: str,
    value: object = "",
    *,
    primary: bool = False,
    symbol: str = "",
    icon_only: bool = False,
) -> str:
    """A data-action button. Icon-only buttons carry aria-label AND title:
    the shell turns title into its themed tooltip, so the control has a name."""
    encoded = (
        value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    )
    classes = "sb-btn sb-btn-primary" if primary else "sb-btn sb-btn-ghost"
    if icon_only:
        classes += " sb-btn-icon"
    accessible = (
        f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"'
        if icon_only
        else ""
    )
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(encoded, quote=True)}"{accessible}>{content}</button>'
    )


def duration(seconds: int, t: Translator) -> str:
    if seconds < 60:
        return tr(t, "uptime.duration.s", n=seconds)
    if seconds < 3600:
        return tr(t, "uptime.duration.min", n=seconds // 60)
    if seconds < 86400:
        return tr(t, "uptime.duration.h", n=seconds // 3600)
    return tr(t, "uptime.duration.d", n=seconds // 86400)


def reason(code: str, t: Translator) -> str:
    """A sample's failure code in words: "HTTP 503", "timeout", "DNS"."""
    if code.isdigit():
        return tr(t, "uptime.reason.http", code=code)
    if code in ("timeout", "dns", "refused", "tls"):
        return t(f"uptime.reason.{code}")
    return t("uptime.reason.error")


def problem(code: str, entry: str, t: Translator) -> str:
    """Why a settings entry was skipped, for the alert and the form error."""
    return tr(t, f"uptime.rejected.{code}", entry=entry)


def percent(value: float | None) -> str:
    if value is None:
        return NO_DATA
    return f"{value:.1f}".rstrip("0").rstrip(".") + " %"


def status_mark(status: str, t: Translator) -> str:
    name, css, key = MARKS[status]
    label = escape(t(key), quote=True)
    return (
        f'<span data-lucide="{name}" class="{css}" role="img"'
        f' aria-label="{label}" title="{label}"></span>'
    )


# --- tile and hover ----------------------------------------------------------


def tile(rows: list[dict], t: Translator) -> str:
    """The basic cover: brand icon, status icon and one line, the same shape in every state."""
    if not rows:
        mark, css, text = "plus", "sb-muted", t("uptime.tile.add")
    elif all(row["status"] == "unknown" for row in rows):
        mark, css, text = "loader-circle", "sb-muted", t("uptime.tile.checking")
    else:
        down = [row["name"] for row in rows if row["status"] == "down"]
        if down:
            mark, css = "circle-x", "sb-crit"
            text = tr(t, "uptime.tile.down", count=len(down), names=", ".join(down))
        else:
            up = sum(1 for row in rows if row["status"] == "up")
            mark, css = "check", "sb-ok"
            text = tr(t, "uptime.tile.up", ok=up, total=len(rows))
    return (
        f'<div class="sb-tile"><span data-lucide="activity" class="sb-accent" aria-hidden="true"></span>'
        f'<span data-lucide="{mark}" class="{css}" aria-hidden="true"></span>'
        f'<span class="{css}" data-marquee style="max-width: 12rem">{escape(text)}</span></div>'
    )


def hover(rows: list[dict], t: Translator) -> str:
    """One line per target, at most five, no controls."""
    if not rows:
        return (
            f'<div class="sb-row">{icon("plus")}'
            f'<span class="sb-muted">{escape(t("uptime.tile.add"))}</span></div>'
        )
    lines = []
    for row in rows[:HOVER_ROWS]:
        if row["status"] == "down":
            value = f'<span class="sb-crit sb-push">{escape(reason(row["reason"], t))}</span>'
        elif row["status"] == "up":
            value = f'<span class="sb-mono sb-push">{row["latencyMs"]} ms</span>'
        else:
            value = f'<span class="sb-muted sb-push">{NO_DATA}</span>'
        lines.append(
            f'<div class="sb-row">{status_mark(row["status"], t)}'
            f'<span>{escape(row["name"])}</span>{value}</div>'
        )
    more = len(rows) - HOVER_ROWS
    tail = (
        f'<p class="sb-meta">{escape(tr(t, "uptime.hover.more", count=more))}</p>'
        if more > 0
        else ""
    )
    return f'<div class="sb-list">{"".join(lines)}</div>{tail}'


# --- flyout ------------------------------------------------------------------


def header(next_iso: str, checking: bool, t: Translator) -> str:
    """Title, the next-check countdown (ticked by the shell) and Check now."""
    if checking:
        meta = escape(t("uptime.checking"))
    else:
        meta = (
            f'{escape(t("uptime.nextCheck"))} <span data-sb-countdown="{next_iso}">'
            '<span class="sb-mono" data-sb-countdown-part="minutes">00</span>:'
            '<span class="sb-mono" data-sb-countdown-part="seconds">00</span></span>'
        )
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("activity")}</span>'
        f'<div><h2 class="sb-title">{escape(t("uptime.title"))}</h2><p class="sb-meta">{meta}</p></div>'
        f'<div class="sb-header-actions">'
        f'{action("check", t("uptime.checkNow"), symbol="refresh-cw", icon_only=True)}</div></div>'
    )


def sparkline(row: dict, t: Translator) -> str:
    points = row["points"]
    if len(points) < 2:
        return ""
    label = tr(
        t,
        "uptime.sparkLabel",
        name=row["name"],
        count=len(points),
        low=min(points),
        high=max(points),
    )
    return (
        f'<span class="sb-spark" data-chart="sparkline" data-points="{",".join(map(str, points))}"'
        f' role="img" aria-label="{escape(label, quote=True)}" style="max-width: 4.5rem"></span>'
    )


def target_row(row: dict, t: Translator) -> str:
    if row["status"] == "down":
        detail = reason(row["reason"], t)
        if row["sinceSeconds"] is not None:
            detail += f" · {duration(row['sinceSeconds'], t)}"
        sub = f'<small class="sb-crit">{escape(detail)}</small>'
        latency = NO_DATA
    else:
        # <code>: a host is literal dotted text, not a locale key.
        sub = f'<small class="sb-faint"><code>{escape(row["host"])}</code></small>'
        latency = f'{row["latencyMs"]} ms' if row["latencyMs"] is not None else NO_DATA
    numbers_title = escape(tr(t, "uptime.uptimeTitle", count=row["checks"]), quote=True)
    return (
        f'<div class="sb-row">{status_mark(row["status"], t)}'
        f'<span class="sb-wrap">{escape(row["name"])}<br>{sub}</span>{sparkline(row, t)}'
        f'<span class="sb-push sb-mono" title="{numbers_title}">{latency}<br>'
        f'<small class="sb-faint">{percent(row["uptimePercent"])}</small></span>'
        f'{action("remove", tr(t, "uptime.remove", name=row["name"]), row["target"], symbol="trash-2", icon_only=True)}'
        "</div>"
    )


def skipped(problems: list[str], t: Translator) -> str:
    if not problems:
        return ""
    return (
        f'<div class="sb-alert sb-alert--warn" role="alert"><span class="sb-alert__icon">{icon("triangle-alert")}</span>'
        f'<div><p class="sb-alert__title">{escape(t("uptime.skippedTitle"))}</p>'
        f'<p class="sb-alert__text">{"<br>".join(escape(text) for text in problems)}</p></div></div>'
    )


def empty(interval: int, t: Translator) -> str:
    return (
        f'<div class="sb-empty"><span class="sb-empty__icon sb-accent">{icon("activity")}</span>'
        f'<p class="sb-empty__title">{escape(t("uptime.emptyTitle"))}</p>'
        f'<p class="sb-empty__text">{escape(tr(t, "uptime.emptyHint", interval=interval))}</p></div>'
    )


def form(error: str, epoch: int, t: Translator) -> str:
    """Name and Target inputs with Add. The epoch in the field names gives a
    fresh, empty form after a successful add; otherwise the shell keeps what
    the user typed across the renders of every check round."""
    name_id, target_id = f"uptime-name-{epoch}", f"uptime-target-{epoch}"
    message = f'<p class="sb-error">{escape(error)}</p>' if error else ""
    return (
        f'<div class="sb-section">{escape(t("uptime.addTitle"))}</div>'
        '<form class="sb-stack">'
        f'<div class="sb-field-stack"><label class="sb-field__label" for="{name_id}">{escape(t("uptime.nameLabel"))}'
        f' <span class="sb-meta">· {escape(t("uptime.optional"))}</span></label>'
        f'<input id="{name_id}" class="sb-input" data-field="name-{epoch}" maxlength="60"'
        f' placeholder="{escape(t("uptime.namePlaceholder"), quote=True)}"></div>'
        f'<div class="sb-field-stack"><label class="sb-field__label" for="{target_id}">{escape(t("uptime.targetLabel"))}</label>'
        f'<input id="{target_id}" class="sb-input" data-field="target-{epoch}" maxlength="500" required'
        f' placeholder="{escape(t("uptime.targetPlaceholder"), quote=True)}" aria-describedby="uptime-target-hint">'
        f'<p class="sb-field__hint" id="uptime-target-hint">{escape(t("uptime.targetHint"))}</p></div>'
        f"{message}"
        f'<div class="sb-cluster"><button type="submit" class="sb-btn sb-btn-primary" data-action="add">'
        f'{icon("plus")}{escape(t("uptime.add"))}</button></div></form>'
    )


def flyout(
    rows: list[dict],
    *,
    problems: list[str],
    next_iso: str,
    checking: bool,
    form_error: str,
    epoch: int,
    interval: int,
    t: Translator,
) -> str:
    if rows:
        body = f'<div class="sb-list">{"".join(target_row(row, t) for row in rows)}</div>'
    else:
        body = empty(interval, t)
    return (
        header(next_iso, checking, t)
        + skipped(problems, t)
        + body
        + form(form_error, epoch, t)
    )


# --- popup -------------------------------------------------------------------


def popup(status: str, text: str, t: Translator) -> str:
    """The state-change toast; its button works like any data-action."""
    name, css, _key = MARKS[status]
    return (
        f'<div class="sb-row"><span data-lucide="{name}" class="{css}" aria-hidden="true"></span>'
        f"<span>{escape(text)}</span>"
        f'{action("check", t("uptime.checkNow"), symbol="refresh-cw", icon_only=True)}</div>'
    )
