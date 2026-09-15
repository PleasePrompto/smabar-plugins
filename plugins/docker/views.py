"""Markup for the Docker plugin: semantic HTML on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing
here touches the SDK, so this module reads and tests without a running bar.
The `snapshot` dict the views take is the plugin's state: containers, phase
("loading", "ok", "offline", "missing"), error, version, updated and busy.
"""

import json
from collections.abc import Callable
from html import escape

from engine import Container, counts, group

Translator = Callable[[str], str]
PLACEHOLDER = "–"
HOVER_NAMES = 5
REASON_LIMIT = 200
# The plugin's whale, drawn for this plugin; the tile, the hover and the flyout header share it.
WHALE_PATHS = (
    '<path d="M3 13.5C3 9.9 6.2 7 10.5 7h2c3.3 0 5.8 2 6.5 5v.5c0 2.8-2.4 4.5-6 4.5H9c-3.6 0-6-1.9-6-4.5Z"/>'
    '<path d="M18.6 11.8c.7-1.4 1.4-2.8 1.9-4.3"/><path d="M20.5 7.5 18.5 5.8M20.5 7.5l2.6-.8"/>'
    '<circle cx="8" cy="12.5" r="1" fill="currentColor" stroke="none"/>'
    '<path d="M9 6.5V4.5M9 4.5 7.5 3M9 4.5l1.5-1.5"/>'
)


def whale(size: str) -> str:
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{WHALE_PATHS}</svg>"
    )


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "docker.running", running=3, total=5)."""
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
    symbol: str = "",
    icon_only: bool = False,
    small: bool = False,
    disabled: bool = False,
) -> str:
    """A data-action button. Icon-only buttons carry aria-label AND title:
    the shell turns title into its themed tooltip, so the control has a name."""
    encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    classes = "sb-btn sb-btn-ghost"
    if icon_only:
        classes += " sb-btn-icon"
    if small:
        classes += " sb-btn--sm"
    accessible = (
        f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"'
        if icon_only
        else ""
    )
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(encoded, quote=True)}"{accessible}{" disabled" if disabled else ""}>'
        f"{content}</button>"
    )


# --- tile and hover ------------------------------------------------------


def tile(snapshot: dict, engine: str, t: Translator) -> str:
    """Cover "basic": the whale, then the one value; the same shape in every state."""
    running, total = counts(snapshot["containers"])
    phase = snapshot["phase"]
    if phase == "missing":
        text, cls = t("docker.tileMissing"), "sb-crit"
    elif phase == "offline":
        text, cls = tr(t, "docker.tileOffline", engine=engine), "sb-crit"
    elif phase == "loading":
        text, cls = PLACEHOLDER, "sb-muted"
    elif total == 0:
        text, cls = t("docker.none"), "sb-muted"
    else:
        text, cls = f"{running}/{total}", "sb-accent" if running else "sb-muted"
    return f'<div class="sb-tile">{whale("1em")}<span class="{cls}">{escape(text)}</span></div>'


def hover(snapshot: dict, engine: str, t: Translator) -> str:
    """One line: how many run, and which."""
    containers = snapshot["containers"]
    running = [item.name for item in containers if item.running]
    phase = snapshot["phase"]
    if phase == "missing":
        text = t("docker.tileMissing")
    elif phase == "offline":
        text = tr(t, "docker.tileOffline", engine=engine)
    elif phase == "loading":
        text = t("docker.loading")
    elif not containers:
        text = t("docker.none")
    elif running:
        names = ", ".join(running[:HOVER_NAMES]) + ("…" if len(running) > HOVER_NAMES else "")
        text = f"{tr(t, 'docker.hoverRunning', count=len(running))} · {names}"
    else:
        text = tr(t, "docker.hoverNone", total=len(containers))
    return f'<div class="sb-row">{whale("1em")}<span class="sb-wrap">{escape(text)}</span></div>'


# --- flyout --------------------------------------------------------------


def flyout(
    snapshot: dict, engine: str, binary: str, interval: int, show_stats: bool, t: Translator
) -> str:
    containers: list[Container] = snapshot["containers"]
    phase = snapshot["phase"]
    parts = [header(snapshot, engine, t)]
    if phase == "missing":
        parts.append(alert(tr(t, "docker.missingTitle", binary=binary), t("docker.missingHint")))
    elif phase == "offline":
        reason = snapshot["error"][:REASON_LIMIT]
        parts.append(
            alert(tr(t, "docker.offlineTitle", engine=engine), f"{reason} {t('docker.offlineHint')}")
        )
    if containers:
        disabled = phase != "ok"
        groups = group(containers)
        # A machine without compose projects has one nameless group: no heading needed.
        headed = len(groups) > 1 or groups[0][0] != ""
        sections = "".join(
            section(project, items, headed, show_stats, snapshot["busy"], disabled, t)
            for project, items in groups
        )
        parts.append(f'<div class="sb-muted">{sections}</div>' if disabled else sections)
    elif phase == "ok":
        parts.append(empty(t))
    elif phase == "loading":
        parts.append(
            f'<div class="sb-row"><span class="sb-spinner" role="status"'
            f' aria-label="{escape(t("docker.loading"), quote=True)}"></span>'
            f'<span class="sb-muted">{escape(t("docker.loading"))}</span></div>'
        )
    if snapshot["updated"]:
        parts.append(
            f'<p class="sb-meta">{escape(tr(t, "docker.updated", time=snapshot["updated"], seconds=interval))}</p>'
        )
    return "".join(parts)


def header(snapshot: dict, engine: str, t: Translator) -> str:
    running, total = counts(snapshot["containers"])
    meta = [tr(t, "docker.engineVersion", version=snapshot["version"])] if snapshot["version"] else []
    if total:
        meta.append(tr(t, "docker.running", running=running, total=total))
    sub = f'<p class="sb-meta">{escape(" · ".join(meta))}</p>' if meta else ""
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{whale("20")}</span>'
        f'<div><h2 class="sb-title">{escape(engine)}</h2>{sub}</div>'
        f'<div class="sb-header-actions">{action("refresh", t("docker.refresh"), symbol="refresh-cw", icon_only=True)}</div>'
        "</div>"
    )


def section(
    project: str,
    items: list[Container],
    headed: bool,
    show_stats: bool,
    busy: set,
    disabled: bool,
    t: Translator,
) -> str:
    rows = "".join(row(item, show_stats, item.id in busy, disabled, t) for item in items)
    heading = f'<div class="sb-section">{escape(project or t("docker.other"))}</div>' if headed else ""
    return f'{heading}<div class="sb-list">{rows}</div>'


def row(item: Container, show_stats: bool, busy: bool, disabled: bool, t: Translator) -> str:
    if busy:
        controls = (
            f'<span class="sb-spinner" role="status" aria-label="{escape(t("docker.working"), quote=True)}"></span>'
        )
    else:
        controls = buttons(item, disabled, t)
    chips = "".join(f'<span class="sb-badge">{escape(port)}</span>' for port in item.ports)
    lines = [
        f'<div class="sb-inline"><span>{escape(item.name)}</span>{badge(item, t)}</div>',
        f'<div class="sb-cluster sb-text-s"><span class="sb-faint">{escape(item.image)}</span>{chips}</div>',
    ]
    if show_stats and item.running and item.cpu is not None:
        lines.append(
            f'<div class="sb-faint sb-text-xs">'
            f'{escape(tr(t, "docker.cpuMem", cpu=f"{item.cpu:.1f} %", mem=item.mem_text))}</div>'
            f'<div class="sb-progress" role="progressbar" aria-label="{escape(t("docker.cpu"), quote=True)}">'
            f'<span style="width: {min(100.0, item.cpu):.0f}%" data-sb-key="cpu-{escape(item.id)}"></span></div>'
        )
    return (
        f'<div class="sb-row"><div class="sb-wrap">{"".join(lines)}</div>'
        f'<div class="sb-inline sb-push">{controls}</div></div>'
    )


def badge(item: Container, t: Translator) -> str:
    """State as a dot badge: text carries the meaning, the color only underlines it."""
    if item.state == "running":
        text = tr(t, "docker.up", age=item.since) if item.since else t("docker.state.running")
        if item.health == "unhealthy":
            return pill("warn", f"{text} · {t('docker.health.unhealthy')}")
        if item.health == "starting":
            return pill("info", f"{text} · {t('docker.health.starting')}")
        return pill("ok", text)
    if item.state in ("paused", "restarting"):
        return pill("warn", t(f"docker.state.{item.state}"))
    if item.state in ("exited", "stopped"):
        if item.exit_code:
            text = (
                tr(t, "docker.exitedCode", code=item.exit_code, age=item.since)
                if item.since
                else tr(t, "docker.state.exitedCode", code=item.exit_code)
            )
            return pill("danger", text)
        return pill("", tr(t, "docker.exited", age=item.since) if item.since else t("docker.state.exited"))
    if item.state == "dead":
        return pill("danger", t("docker.state.dead"))
    if item.state in ("created", "removing", "stopping"):
        return pill("", t(f"docker.state.{item.state}"))
    return pill("", item.state)


def pill(kind: str, text: str) -> str:
    classes = f"sb-badge sb-badge--{kind}" if kind else "sb-badge"
    return f'<span class="{classes}">{escape(text)}</span>'


def buttons(item: Container, disabled: bool, t: Translator) -> str:
    if item.state in ("running", "paused", "restarting"):
        return action(
            "stop", tr(t, "docker.stop", name=item.name), item.id,
            symbol="square", icon_only=True, small=True, disabled=disabled,
        ) + action(
            "restart", tr(t, "docker.restart", name=item.name), item.id,
            symbol="rotate-cw", icon_only=True, small=True, disabled=disabled,
        )
    return action(
        "start", tr(t, "docker.start", name=item.name), item.id,
        symbol="play", icon_only=True, small=True, disabled=disabled,
    )


def empty(t: Translator) -> str:
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon sb-accent">{icon("box")}</div>'
        f'<p class="sb-empty__title">{escape(t("docker.emptyTitle"))}</p>'
        f'<p class="sb-empty__text">{escape(t("docker.emptyHint"))}</p></div>'
    )


def alert(title: str, text: str) -> str:
    return (
        f'<div class="sb-alert sb-alert--danger" role="alert"><span class="sb-alert__icon">{icon("triangle-alert")}</span>'
        f'<div><p class="sb-alert__title">{escape(title)}</p><p class="sb-alert__text">{escape(text)}</p></div></div>'
    )


# --- popup ---------------------------------------------------------------


def failure(label: str, reason: str, t: Translator) -> str:
    """The toast after a failed start/stop/restart: what failed, and the engine's first line."""
    return (
        f'<div class="sb-row">{icon("triangle-alert")}<span class="sb-wrap">'
        f"<b>{escape(tr(t, 'docker.failed', action=label))}</b><br>"
        f'<small class="sb-faint">{escape(reason[:REASON_LIMIT])}</small></span></div>'
    )
