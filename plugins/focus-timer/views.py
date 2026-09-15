"""Markup for the Focus Timer: semantic HTML on the smabar UI kit, no SDK imports.

Every function returns a string plugin.py pushes with app.render. A running
phase carries data-sb-countdown, so the shell ticks the digits and the plugin
renders only on real state changes.
"""

from collections.abc import Callable
from datetime import datetime
from html import escape

import model

Translator = Callable[[str], str]

PHASE_NAME = {
    model.IDLE: "timer.idle",
    model.FOCUS: "timer.focus",
    model.SHORT_BREAK: "timer.shortBreak",
    model.LONG_BREAK: "timer.longBreak",
}
PHASE_ICON = {
    model.IDLE: "timer",
    model.FOCUS: "flame",
    model.SHORT_BREAK: "sparkles",
    model.LONG_BREAK: "moon",
}
PHASE_TONE = {model.FOCUS: "sb-accent", model.SHORT_BREAK: "sb-ok", model.LONG_BREAK: "sb-ok"}


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "timer.today", count=3)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str, tone: str = "") -> str:
    classes = f' class="{tone}"' if tone else ""
    return f'<span data-lucide="{name}"{classes} aria-hidden="true"></span>'


def action(
    name: str,
    label: str,
    value: str = "",
    *,
    primary: bool = False,
    symbol: str = "",
    disabled_reason: str = "",
) -> str:
    """A data-action button; a disabled one explains itself through its title."""
    classes = "sb-btn sb-btn-primary" if primary else "sb-btn"
    state = (
        f' disabled title="{escape(disabled_reason, quote=True)}"' if disabled_reason else ""
    )
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(value, quote=True)}"{state}>'
        f"{icon(symbol) if symbol else ''}{escape(label)}</button>"
    )


def clock(seconds: int) -> str:
    """mm:ss, or hh:mm:ss from an hour upwards."""
    hours, rest = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def countdown(state: dict, now: datetime, classes: str) -> str:
    """The remaining time: the shell ticks a running phase, a paused one is static."""
    remaining = model.remaining_seconds(state, now)
    attr = f' class="{classes}"' if classes else ""
    if not model.is_running(state):
        return f"<span{attr}>{clock(remaining)}</span>"
    target = model.ends_at(state).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    hours, rest = divmod(remaining, 3600)
    minutes, secs = divmod(rest, 60)
    parts = (
        f'<span data-sb-countdown-part="hours">{hours:02d}</span>:' if hours else ""
    ) + (
        f'<span data-sb-countdown-part="minutes">{minutes:02d}</span>:'
        f'<span data-sb-countdown-part="seconds">{secs:02d}</span>'
    )
    return f'<span{attr} data-sb-countdown="{target}" role="timer">{parts}</span>'


def phase_glyph(state: dict) -> str:
    phase = state["phase"]
    if phase == model.IDLE:
        return icon("timer")
    if model.is_running(state):
        return icon(PHASE_ICON[phase], PHASE_TONE[phase])
    return icon("pause", "sb-muted")


def blocks_today(count: int, t: Translator) -> str:
    return t("timer.oneBlockToday") if count == 1 else tr(t, "timer.blocksToday", count=count)


def tile(state: dict, now: datetime, t: Translator) -> str:
    """Basic cover: the timer glyph, a phase glyph and the countdown; idle shows the day's count.

    The timer glyph leads in every state; the second glyph marks the phase.
    """
    if state["phase"] == model.IDLE:
        count = state["completedToday"]
        today = (
            f'<span class="sb-muted">{escape(tr(t, "timer.today", count=count))}</span>'
            if count
            else ""
        )
        return f'<div class="sb-tile">{icon("timer")}<span>{escape(t("timer.focus"))}</span>{today}</div>'
    label = ""
    if state["phase"] == model.FOCUS and model.is_running(state) and state["label"]:
        label = (
            f'<span class="sb-muted" data-marquee style="max-width: 8rem">'
            f'{escape(state["label"])}</span>'
        )
    return f'<div class="sb-tile">{icon("timer")}{phase_glyph(state)}{countdown(state, now, "")}{label}</div>'


def hover(state: dict, now: datetime, t: Translator) -> str:
    """One line: phase · time left · blocks today."""
    name = escape(t(PHASE_NAME[state["phase"]]))
    left = ""
    if state["phase"] != model.IDLE:
        left = (
            f'<span class="sb-muted">{countdown(state, now, "")} {escape(t("timer.left"))}</span>'
        )
    return (
        f'<div class="sb-row">{phase_glyph(state)}<span>{name}</span>{left}'
        f'<span class="sb-faint sb-push">{escape(blocks_today(state["completedToday"], t))}</span></div>'
    )


def start_label(phase: str, t: Translator) -> str:
    return t("timer.startFocus" if phase == model.FOCUS else "timer.startBreak")


def header(state: dict, now: datetime, t: Translator) -> str:
    phase = state["phase"]
    if model.is_running(state):
        ends = model.ends_at(state).astimezone().strftime("%H:%M")
        meta = tr(t, "timer.endsAt", time=ends)
    elif phase == model.IDLE:
        meta = blocks_today(state["completedToday"], t)
    elif model.is_pending(state):
        meta = t("timer.pending")
    else:
        meta = t("timer.paused")
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("timer")}</span>'
        f'<div><h2 class="sb-title">{escape(t(PHASE_NAME[phase]))}</h2>'
        f'<p class="sb-meta">{escape(meta)}</p></div></div>'
    )


def controls(state: dict, t: Translator) -> str:
    phase = state["phase"]
    if phase == model.IDLE:
        primary = action("start", t("timer.start"), primary=True, symbol="play")
    elif model.is_running(state):
        primary = action("pause", t("timer.pause"), primary=True, symbol="pause")
    elif model.is_pending(state):
        primary = action("start", start_label(phase, t), primary=True, symbol="play")
    else:
        primary = action("resume", t("timer.resume"), primary=True, symbol="play")
    reason = t("timer.nothingRunning") if phase == model.IDLE else ""
    return (
        '<div class="sb-cluster">'
        + primary
        + action("skip", t("timer.skip"), symbol="skip-forward", disabled_reason=reason)
        + action("reset", t("timer.reset"), symbol="rotate-cw", disabled_reason=reason)
        + "</div>"
    )


def label_form(state: dict, t: Translator) -> str:
    return (
        '<form class="sb-stack"><div class="sb-field-stack">'
        f'<label class="sb-field__label" for="label">{escape(t("timer.labelLabel"))}'
        f' <span class="sb-meta">· {escape(t("timer.optional"))}</span></label>'
        '<div class="sb-field">'
        f'<input id="label" class="sb-input" data-field="label" maxlength="80"'
        f' value="{escape(state["label"], quote=True)}"'
        f' placeholder="{escape(t("timer.labelPlaceholder"), quote=True)}">'
        f'<button type="submit" class="sb-btn" data-action="save_label">{escape(t("timer.save"))}</button>'
        "</div></div></form>"
    )


def stats(state: dict, t: Translator) -> str:
    return (
        f'<div class="sb-section">{escape(t("timer.todaySection"))}</div>'
        '<div class="sb-kpi-grid">'
        f'<div class="sb-kpi"><span class="sb-kpi-value" data-sb-tween data-sb-key="blocks">{state["completedToday"]}</span>'
        f'<span class="sb-kpi-label">{escape(t("timer.blocks"))}</span></div>'
        f'<div class="sb-kpi"><span class="sb-kpi-value" data-sb-tween data-sb-key="minutes">{state["focusMinutesToday"]}</span>'
        f'<span class="sb-kpi-label">{escape(t("timer.focusMinutes"))}</span></div></div>'
    )


def up_next(state: dict, config: dict, t: Translator) -> str:
    following = model.next_phase(state, config)
    minutes = model.phase_seconds(config, following) // 60
    every = max(1, int(config["longBreakEvery"]))
    done = state["completedToday"] + (
        1 if state["phase"] == model.FOCUS and not state["extension"] else 0
    )
    until_long = every - (done % every)
    if following == model.LONG_BREAK:
        note = t("timer.longBreakNext")
    elif until_long == 1:
        note = t("timer.longBreakAfterOne")
    else:
        note = tr(t, "timer.longBreakAfter", count=until_long)
    return (
        f'<div class="sb-section">{escape(t("timer.upNext"))}</div>'
        f'<div class="sb-row">{icon(PHASE_ICON[following])}'
        f'<span>{escape(t(PHASE_NAME[following]))}</span>'
        f'<span class="sb-muted sb-push">{escape(tr(t, "timer.minutes", count=minutes))}</span></div>'
        f'<p class="sb-meta">{escape(note)}</p>'
    )


def flyout(state: dict, now: datetime, config: dict, t: Translator) -> str:
    phase = state["phase"]
    if phase == model.IDLE:
        digits = f'<span class="sb-text-hero sb-muted">{clock(model.phase_seconds(config, model.FOCUS))}</span>'
    else:
        tone = PHASE_TONE[phase] if model.is_running(state) else "sb-dim"
        digits = countdown(state, now, f"sb-text-hero {tone}")
    label = (
        f'<p class="sb-muted sb-wrap">{escape(state["label"])}</p>'
        if state["label"] and phase in (model.IDLE, model.FOCUS)
        else ""
    )
    return (
        header(state, now, t)
        + f'<div class="sb-card sb-center">{digits}{label}</div>'
        + controls(state, t)
        + label_form(state, t)
        + stats(state, t)
        + up_next(state, config, t)
    )


def popup(ended: str, state: dict, config: dict, t: Translator) -> str:
    """The phase-done toast; its buttons are ordinary data-actions."""
    pending = state["phase"]
    minutes = model.phase_seconds(config, pending) // 60
    title = t("timer.focusDone" if ended == model.FOCUS else "timer.breakDone")
    line = (
        f'{tr(t, "timer.nextIs", phase=t(PHASE_NAME[pending]), minutes=minutes)}'
        f' · {blocks_today(state["completedToday"], t)}'
    )
    buttons = action("start", start_label(pending, t), primary=True, symbol="play")
    if ended == model.FOCUS:
        buttons += action("skip", t("timer.skipBreak"), "start", symbol="skip-forward")
    buttons += action("extend", t("timer.plusFive"), ended, symbol="plus")
    return (
        f'<div class="sb-inline sb-meta">{icon("timer")}<span>{escape(t("timer.title"))}</span></div>'
        f'<h2 class="sb-title">{escape(title)}</h2>'
        f'<p class="sb-dim">{escape(line)}</p>'
        f'<div class="sb-cluster">{buttons}</div>'
    )
