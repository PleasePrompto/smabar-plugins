"""Markup for Clipboard History: semantic HTML on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing here
touches the SDK, so the module reads and tests without a running bar.
"""

import json
import re
import time
from collections.abc import Callable
from html import escape

Translator = Callable[[str], str]

TILE_CHARS = 28
HOVER_CHARS = 40
HOVER_ROWS = 3
PREVIEW_LINES = 2
PREVIEW_CHARS = 56
FLYOUT_BUDGET = 700_000  # bytes of row markup; the host refuses render messages above 1 MiB
LIST_ID = "clip-list"
DIALOG_ID = "clip-clear"

# URLs, hex colours, prompt lines, CLI flags and code punctuation.
CODE_MARKERS = re.compile(
    r"^(https?://|www\.|#[0-9a-fA-F]{3,8}$|[$>] )|[{};]|</|\(\)|=>|->|://|\s--?[a-zA-Z]|^\s{2,}\S",
    re.MULTILINE,
)


def clipboard_svg(size: str) -> str:
    """The plugin's clipboard glyph (Lucide style), sized for the tile or the header badge."""
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/>'
        '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
        '<path d="M9 12h6"/><path d="M9 16h6"/></svg>'
    )


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "clip.entries", n=3)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str, cls: str = "") -> str:
    classes = f' class="{cls}"' if cls else ""
    return f'<span data-lucide="{name}"{classes} aria-hidden="true"></span>'


def action(
    name: str,
    label: str,
    value: object = "",
    *,
    symbol: str = "",
    icon_only: bool = False,
    pressed: bool | None = None,
) -> str:
    """A data-action button. Icon-only buttons carry aria-label AND title:
    the shell turns title into its themed tooltip, so the control has a name."""
    encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    classes = "sb-btn sb-btn-ghost sb-btn-icon" if icon_only else "sb-btn sb-btn-ghost"
    accessible = (
        f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"'
        if icon_only
        else ""
    )
    if pressed is not None:
        accessible += f' aria-pressed="{str(pressed).lower()}"'
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(encoded, quote=True)}"{accessible}>{content}</button>'
    )


def one_line(text: str, limit: int) -> str:
    """Whitespace and newlines collapsed to single spaces, cut with an ellipsis."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def looks_like_code(text: str) -> bool:
    return CODE_MARKERS.search(text) is not None


def relative_time(at: int, now: int, t: Translator) -> str:
    seconds = max(0, int(now) - int(at))
    if seconds < 60:
        return t("clip.justNow")
    if seconds < 3600:
        return tr(t, "clip.minutesAgo", n=seconds // 60)
    if seconds < 86400:
        return tr(t, "clip.hoursAgo", n=seconds // 3600)
    if seconds < 7 * 86400:
        return tr(t, "clip.daysAgo", n=seconds // 86400)
    return time.strftime("%Y-%m-%d", time.localtime(at))


def preview(text: str) -> str:
    """The first two non-empty lines, shortened, as escaped HTML."""
    lines = [line.strip() for line in text.splitlines() if line.strip()][:PREVIEW_LINES]
    budget = PREVIEW_CHARS // max(1, len(lines))
    return "<br>".join(escape(one_line(line, budget)) for line in lines)


def size_note(text: str, t: Translator) -> str:
    """"N lines · N chars" for texts the preview cannot show whole; empty otherwise."""
    lines = text.count("\n") + 1
    if lines > PREVIEW_LINES:
        return tr(t, "clip.size", lines=lines, chars=len(text))
    if len(text) > PREVIEW_CHARS:
        return tr(t, "clip.chars", chars=len(text))
    return ""


def tile(latest: str | None, paused: bool, missing_tool: str, t: Translator) -> str:
    """The basic cover: the clipboard glyph, then one line of text, in every state."""
    if missing_tool:
        body = icon("triangle-alert", "sb-crit") + (
            f'<span class="sb-crit">{escape(tr(t, "clip.installTool", tool=missing_tool))}</span>'
        )
    elif paused:
        body = icon("pause", "sb-muted") + f'<span class="sb-muted">{escape(t("clip.paused"))}</span>'
    elif latest is None:
        body = f'<span class="sb-muted">{escape(t("clip.empty"))}</span>'
    else:
        body = f"<span>{escape(one_line(latest, TILE_CHARS))}</span>"
    return f'<div class="sb-tile">{clipboard_svg("1em")}{body}</div>'


def hover(entries: list[dict], paused: bool, now: int, t: Translator) -> str:
    """The latest three entries, one line each; no controls."""
    rows = []
    if paused:
        rows.append(
            f'<div class="sb-row">{icon("pause", "sb-muted")}'
            f'<span class="sb-muted">{escape(t("clip.paused"))}</span></div>'
        )
    for entry in entries[:HOVER_ROWS]:
        mono = ' class="sb-mono"' if looks_like_code(entry["text"]) else ""
        rows.append(
            f'<div class="sb-row">{icon("pin") if entry["pinned"] else ""}'
            f"<span{mono}>{escape(one_line(entry['text'], HOVER_CHARS))}</span>"
            f'<span class="sb-faint sb-push">{escape(relative_time(entry["at"], now, t))}</span></div>'
        )
    if not entries:
        rows.append(f'<div class="sb-row"><span class="sb-muted">{escape(t("clip.empty"))}</span></div>')
    return f'<div class="sb-list">{"".join(rows)}</div>'


def header(count: int, unpinned: int, paused: bool, t: Translator) -> str:
    badges = f'<span class="sb-badge" title="{escape(tr(t, "clip.entries", n=count), quote=True)}">{count}</span>'
    if paused:
        badges += f'<span class="sb-badge sb-badge-warning">{escape(t("clip.paused"))}</span>'
    toggle = action(
        "pause",
        t("clip.resume" if paused else "clip.pause"),
        "false" if paused else "true",
        symbol="play" if paused else "pause",
        icon_only=True,
    )
    clear_label = escape(t("clip.clear" if unpinned else "clip.nothingToClear"), quote=True)
    clear = (
        f'<button type="button" class="sb-btn sb-btn-ghost sb-btn-icon" commandfor="{DIALOG_ID}"'
        f' command="show-modal" title="{clear_label}" aria-label="{clear_label}"'
        f'{"" if unpinned else " disabled"}>{icon("trash-2")}</button>'
    )
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{clipboard_svg("18")}</span>'
        f'<span class="sb-title">{escape(t("clip.title"))}</span>{badges}'
        f'<div class="sb-header-actions">{toggle}{clear}</div></div>'
    )


def clear_dialog(unpinned: int, t: Translator) -> str:
    return (
        f'<dialog class="sb-modal sb-modal--sm" id="{DIALOG_ID}" aria-labelledby="{DIALOG_ID}-title">'
        f'<div class="sb-modal__header"><h3 class="sb-modal__title" id="{DIALOG_ID}-title">'
        f'{escape(t("clip.clearTitle"))}</h3></div>'
        f'<div class="sb-modal__body"><p>{escape(tr(t, "clip.clearText", n=unpinned))}</p></div>'
        f'<div class="sb-modal__footer"><button type="button" class="sb-btn" commandfor="{DIALOG_ID}"'
        f' command="close">{escape(t("clip.cancel"))}</button>'
        f'<button type="button" class="sb-btn sb-btn-danger" commandfor="{DIALOG_ID}" command="close"'
        f' data-action="clear">{escape(t("clip.confirmClear"))}</button></div></dialog>'
    )


def row(entry: dict, now: int, t: Translator) -> str:
    """One table row: preview and meta on the left, the three icon actions on the right."""
    text = entry["text"]
    meta = " · ".join(part for part in (relative_time(entry["at"], now, t), size_note(text, t)) if part)
    pinned = entry["pinned"]
    mono = " sb-mono" if looks_like_code(text) else ""
    copy_label = escape(t("clip.copy"), quote=True)
    return (
        f'<tr><td><span class="sb-wrap{mono}">{preview(text)}</span>'
        f'<div class="sb-meta">{icon("pin") + " " if pinned else ""}{escape(meta)}</div></td>'
        '<td class="sb-table__num"><span class="sb-inline">'
        f'<button type="button" class="sb-btn sb-btn-ghost sb-btn-icon" data-sb-copy-text="{escape(text, quote=True)}"'
        f' title="{copy_label}" aria-label="{copy_label}">{icon("copy")}</button>'
        + action(
            "pin",
            t("clip.unpin" if pinned else "clip.pin"),
            {"id": entry["id"], "pinned": not pinned},
            symbol="pin",
            icon_only=True,
            pressed=pinned,
        )
        + action("delete", t("clip.delete"), entry["id"], symbol="trash-2", icon_only=True)
        + "</span></td></tr>"
    )


def flyout(
    entries: list[dict], unpinned: int, paused: bool, error: str, now: int, t: Translator
) -> str:
    """Header with actions, the confirm dialog, an optional error, the searchable list."""
    parts = [header(len(entries), unpinned, paused, t), clear_dialog(unpinned, t)]
    if error:
        parts.append(
            f'<div class="sb-alert sb-alert--danger" role="alert">{icon("triangle-alert")}'
            f'<span class="sb-alert__text">{escape(error)}</span></div>'
        )
    if not entries:
        parts.append(
            f'<div class="sb-empty"><span class="sb-empty__icon">{icon("copy")}</span>'
            f'<span class="sb-empty__title">{escape(t("clip.emptyTitle"))}</span>'
            f'<span class="sb-empty__text">{escape(t("clip.emptyText"))}</span></div>'
        )
        return "".join(parts)
    parts.append(
        f'<input class="sb-input" type="search" data-field="q" data-sb-filter="#{LIST_ID}"'
        f' placeholder="{escape(t("clip.searchPlaceholder"), quote=True)}"'
        f' aria-label="{escape(t("clip.search"), quote=True)}">'
    )
    rows: list[str] = []
    budget = FLYOUT_BUDGET
    for entry in entries:
        html = row(entry, now, t)
        budget -= len(html.encode("utf-8"))
        if budget < 0:
            break
        rows.append(html)
    parts.append(
        f'<div class="sb-table-wrap"><table class="sb-table sb-table--hover" id="{LIST_ID}"'
        f' aria-label="{escape(t("clip.title"), quote=True)}"><tbody>{"".join(rows)}</tbody></table>'
        f'<p class="sb-table-filter__empty" role="status" hidden>{escape(t("clip.noMatch"))}</p></div>'
    )
    if len(rows) < len(entries):
        parts.append(f'<p class="sb-meta">{escape(tr(t, "clip.hidden", n=len(entries) - len(rows)))}</p>')
    return "".join(parts)
