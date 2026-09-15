"""Markup for Keep Awake: semantic HTML on the smabar UI kit, no SDK access.

Every function returns a string the plugin pushes with app.render. The timed
tile and the flyout carry a data-sb-countdown the shell ticks itself, so their
HTML stays identical for the whole session and the DOM is never rebuilt.
"""

from collections.abc import Callable
from datetime import datetime
from html import escape

Translator = Callable[[str], str]

COFFEE = (
    '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M10 2v2"/><path d="M14 2v2"/>'
    '<path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/>'
    '<path d="M6 2v2"/></svg>'
)
DURATIONS = (30, 60, 120, 240, 0)  # minutes; 0 = until switched off


def tr(t: Translator, key: str, **values: object) -> str:
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def local_iso(end: float) -> str:
    return datetime.fromtimestamp(end).strftime("%Y-%m-%dT%H:%M:%S")


def local_time(end: float) -> str:
    return datetime.fromtimestamp(end).strftime("%H:%M")


def countdown(end: float, seconds: bool) -> str:
    parts = ["hours", "minutes", "seconds"] if seconds else ["hours", "minutes"]
    slots = ":".join(f'<span data-sb-countdown-part="{part}"></span>' for part in parts)
    return f'<span data-sb-countdown="{local_iso(end)}">{slots}</span>'


def duration_label(minutes: int, t: Translator) -> str:
    if minutes == 0:
        return t("awake.untilOff")
    if minutes < 60:
        return tr(t, "awake.minutes", n=minutes)
    return tr(t, "awake.hours", n=minutes // 60)


def tile(state: dict, t: Translator) -> str:
    """Basic cover: the coffee glyph, then one value; the shape never changes."""
    if state["busy"]:
        body = '<span class="sb-muted">…</span>'
    elif not state["on"]:
        body = f'<span class="sb-muted">{escape(t("awake.off"))}</span>'
    elif state["end_at"] is None:
        body = f'<span class="sb-accent">{escape(t("awake.on"))}</span>'
    else:
        body = f'<span class="sb-accent">{escape(t("awake.on"))} · {countdown(state["end_at"], False)}</span>'
    return f'<div class="sb-tile">{COFFEE}{body}</div>'


def hover(state: dict, minutes_left: int | None, t: Translator) -> str:
    if not state["on"]:
        text = t("awake.hoverOff")
    elif minutes_left is None:
        text = t("awake.hoverUntilOff")
    else:
        text = tr(t, "awake.hoverOn", minutes=minutes_left)
    return f'<div class="sb-row">{COFFEE}<span>{escape(text)}</span></div>'


def flyout(state: dict, t: Translator) -> str:
    on = state["on"]
    parts = [
        f'<div class="sb-header"><span class="sb-icon-badge">{COFFEE}</span>'
        f'<span class="sb-title">{escape(t("awake.title"))}</span></div>'
    ]
    if state["error"]:
        parts.append(
            '<div class="sb-alert sb-alert--danger" role="alert"><div>'
            f'<div class="sb-alert__title">{escape(t("awake.errorTitle"))}</div>'
            f'<div class="sb-alert__text">{escape(state["error"])}</div></div></div>'
        )
    end = state["end_at"]
    if on and end is not None:
        parts.append(
            f'<div class="sb-hero"><small>{escape(tr(t, "awake.endsAt", time=local_time(end)))}</small>'
            f"<h1>{countdown(end, True)}</h1></div>"
        )
    elif on:
        parts.append(
            f'<div class="sb-hero"><small>{escape(t("awake.untilSwitchedOff"))}</small>'
            f"<h1>{escape(t('awake.on'))}</h1></div>"
        )
    else:
        parts.append(
            f'<div class="sb-card"><p class="sb-title">{escape(t("awake.off"))}</p>'
            f'<p class="sb-dim">{escape(t("awake.offHint"))}</p></div>'
        )
    checked = " checked" if on else ""
    target = "off" if on else "on"
    parts.append(
        f'<label class="sb-switch"><input type="checkbox" role="switch" data-action="toggle"'
        f' data-value="{target}"{checked}> {escape(t("awake.switch"))}</label>'
    )
    parts.append(f'<div class="sb-section">{escape(t("awake.duration" if on else "awake.startFor"))}</div>')
    chips = []
    for minutes in DURATIONS:
        selected = on and minutes == state["minutes"]
        chips.append(
            f'<button type="button" class="sb-chip{" is-selected" if selected else ""}"'
            f' aria-pressed="{str(selected).lower()}" data-action="duration" data-value="{minutes}">'
            f"{escape(duration_label(minutes, t))}</button>"
        )
    parts.append(f'<div class="sb-cluster">{"".join(chips)}</div>')
    note = tr(t, "awake.mechanism", mechanism=state["mechanism"]) if on else t("awake.startsOff")
    parts.append(f'<p class="sb-meta">{escape(note)}</p>')
    return "".join(parts)


def popup(t: Translator) -> str:
    return (
        f'<div class="sb-row">{COFFEE}<div><p class="sb-title">{escape(t("awake.ended"))}</p>'
        f'<p class="sb-meta">{escape(t("awake.endedText"))}</p></div></div>'
    )
