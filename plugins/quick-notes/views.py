"""Markup for Quick Notes: semantic HTML on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing
here touches the SDK or the file system, so this module renders in a test
without a running bar. Layout, spacing and type come from sb-* classes.
"""

import hashlib
import time
from collections.abc import Callable
from html import escape

from model import MAX_TEXT, Note

Translator = Callable[[str], str]

TILE_CHARS = 24
TITLE_CHARS = 60
PREVIEW_CHARS = 40
HOVER_LINES = 3


def note_glyph(size: str, cls: str = "") -> str:
    """The folded sticky note, the plugin's own mark: 1em in the tile, 36px in the empty state."""
    classes = f' class="{cls}"' if cls else ""
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}"{classes} fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M5 3h14a2 2 0 0 1 2 2v9l-7 7H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M14 21v-5a2 2 0 0 1 2-2h5"/><path d="M8 9h8M8 13h5"/></svg>'
    )


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "notes.count", n=3)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str, cls: str = "") -> str:
    classes = f' class="{cls}"' if cls else ""
    return f'<span data-lucide="{name}"{classes} aria-hidden="true"></span>'


def action(name: str, label: str, *, symbol: str = "", icon_only: bool = False) -> str:
    """A ghost data-action button. Icon-only buttons carry aria-label AND title:
    the shell turns title into its themed tooltip, so the control has a name."""
    classes = "sb-btn sb-btn-ghost" + (" sb-btn-icon sb-btn--sm" if icon_only else "")
    named = f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"' if icon_only else ""
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return f'<button type="button" class="{classes}" data-action="{escape(name, quote=True)}"{named}>{content}</button>'


def token(note_id: str) -> str:
    """A DOM-safe id for a note, since a note id may be any file stem."""
    return hashlib.blake2b(note_id.encode("utf-8"), digest_size=6).hexdigest()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def name(note: Note, t: Translator) -> str:
    return note.title or t("notes.untitled")


def when(updated: float, now: float, t: Translator) -> str:
    """Relative age up to a week, then the plain date."""
    seconds = max(0.0, now - updated)
    if seconds < 60:
        return t("notes.justNow")
    if seconds < 3600:
        return tr(t, "notes.minutesAgo", n=int(seconds // 60))
    if seconds < 86400:
        return tr(t, "notes.hoursAgo", n=int(seconds // 3600))
    if seconds < 7 * 86400:
        return tr(t, "notes.daysAgo", n=int(seconds // 86400))
    return time.strftime("%Y-%m-%d", time.localtime(updated))


def tile_label(notes: list[Note], mode: str, t: Translator) -> str:
    """One calm line: the pinned (else latest) title, the latest title, or a count."""
    if not notes:
        return t("notes.none")
    if mode == "count":
        return tr(t, "notes.countOne" if len(notes) == 1 else "notes.count", n=len(notes))
    note = max(notes, key=lambda item: item.updated) if mode == "latest" else notes[0]
    return clip(name(note, t), TILE_CHARS)


def tile(notes: list[Note], mode: str, t: Translator) -> str:
    """The basic cover: the sticky-note glyph, then one calm line, in every state."""
    return f'<div class="sb-tile">{note_glyph("1em", "sb-accent")}<span>{escape(tile_label(notes, mode, t))}</span></div>'


def hover(note: Note | None, t: Translator) -> str:
    """The first lines of the featured note, no controls."""
    if note is None:
        return f'<div class="sb-row">{icon("file-text")}<span class="sb-muted">{escape(t("notes.none"))}</span></div>'
    lines = [line.strip() for line in note.text.splitlines() if line.strip()][1:HOVER_LINES]
    body = "".join(f'<p class="sb-muted sb-text-s sb-wrap">{escape(clip(line, 80))}</p>' for line in lines)
    return f'<p class="sb-wrap"><strong>{escape(name(note, t))}</strong></p>{body}'


def header(count: int, t: Translator) -> str:
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("file-text")}</span>'
        f'<span class="sb-title">{escape(t("notes.title"))}</span>'
        f'<span class="sb-badge">{count}</span>'
        f'<div class="sb-header-actions"><button type="button" class="sb-btn sb-btn-primary sb-btn-icon"'
        f' commandfor="compose" command="show-modal" title="{escape(t("notes.compose"), quote=True)}"'
        f' aria-label="{escape(t("notes.compose"), quote=True)}">{icon("plus")}</button></div></div>'
    )


def alert(message: str) -> str:
    return (
        f'<div class="sb-alert sb-alert--danger" role="alert">'
        f'<span class="sb-alert__icon" aria-hidden="true">{icon("circle-alert")}</span>'
        f'<div class="sb-alert__text">{escape(message)}</div></div>'
    )


def quick_form(field: str, t: Translator) -> str:
    """The two-second jot: a textarea and its Save button."""
    return (
        '<form class="sb-stack"><div class="sb-field-stack">'
        f'<label class="sb-field__label" for="{field}">{escape(t("notes.quickLabel"))}</label>'
        f'<textarea id="{field}" class="sb-textarea" data-field="{field}" rows="2" required'
        f' maxlength="{MAX_TEXT}" placeholder="{escape(t("notes.quickPlaceholder"), quote=True)}"'
        f' aria-describedby="{field}-hint"></textarea>'
        f'<p class="sb-field__hint" id="{field}-hint">{escape(t("notes.quickHint"))}</p></div>'
        f'<div class="sb-cluster"><button type="submit" class="sb-btn sb-btn-primary" data-action="add">'
        f"{icon('save')}{escape(t('notes.save'))}</button></div></form>"
    )


def editor(dialog_id: str, title: str, field: str, text: str, save_action: str, t: Translator) -> str:
    """A modal editor; its Save button closes the dialog and sends the fields."""
    return (
        f'<dialog class="sb-modal" id="{dialog_id}" aria-labelledby="{dialog_id}-title">'
        f'<div class="sb-modal__header"><h3 class="sb-modal__title" id="{dialog_id}-title">{escape(title)}</h3></div>'
        f'<div class="sb-modal__body"><div class="sb-field-stack">'
        f'<label class="sb-field__label" for="{field}">{escape(t("notes.textLabel"))}</label>'
        f'<textarea id="{field}" class="sb-textarea" data-field="{field}" rows="8" maxlength="{MAX_TEXT}"'
        f' placeholder="{escape(t("notes.quickPlaceholder"), quote=True)}" autofocus>{escape(text)}</textarea>'
        f"</div></div>"
        f'<div class="sb-modal__footer"><button type="button" class="sb-btn" commandfor="{dialog_id}" command="close">'
        f"{escape(t('notes.cancel'))}</button>"
        f'<button type="button" class="sb-btn sb-btn-primary" commandfor="{dialog_id}" command="close"'
        f' data-action="{escape(save_action, quote=True)}">{icon("save")}{escape(t("notes.save"))}</button>'
        f"</div></dialog>"
    )


def row(note: Note, now: float, t: Translator) -> str:
    """Title on the first line; preview, age and the icon actions share the second."""
    tok = token(note.id)
    meta = " · ".join(part for part in (clip(note.preview, PREVIEW_CHARS), when(note.updated, now, t)) if part)
    pin = icon("pin", "sb-accent") + " " if note.pinned else ""
    small = "sb-btn sb-btn-ghost sb-btn-icon sb-btn--sm"
    copy = (
        f'<button type="button" class="{small}" data-sb-copy-text="{escape(note.text, quote=True)}"'
        f' title="{escape(t("notes.copy"), quote=True)}" aria-label="{escape(t("notes.copy"), quote=True)}">{icon("copy")}</button>'
    )
    edit = (
        f'<button type="button" class="{small}" commandfor="edit-{tok}" command="show-modal"'
        f' title="{escape(t("notes.edit"), quote=True)}" aria-label="{escape(t("notes.edit"), quote=True)}">{icon("pencil")}</button>'
    )
    return (
        f'<tr><td class="sb-wrap"><div>{pin}{escape(clip(name(note, t), TITLE_CHARS))}</div>'
        f'<div class="sb-inline"><span class="sb-muted sb-text-s sb-wrap">{escape(meta)}</span>'
        f'<span class="sb-inline sb-push">'
        + action(f"pin:{note.id}", t("notes.unpin" if note.pinned else "notes.pin"), symbol="pin", icon_only=True)
        + copy
        + edit
        + action(f"delete:{note.id}", t("notes.delete"), symbol="trash-2", icon_only=True)
        + "</span></div></td></tr>"
    )


def note_table(notes: list[Note], now: float, t: Translator) -> str:
    """A filterable table (data-sb-filter needs tbody rows), newest first."""
    rows = "".join(row(note, now, t) for note in notes)
    return (
        f'<input class="sb-input" type="search" data-field="query" data-sb-filter="#note-list"'
        f' placeholder="{escape(t("notes.filter"), quote=True)}" aria-label="{escape(t("notes.filter"), quote=True)}">'
        f'<div class="sb-table-wrap"><table class="sb-table sb-table--hover" id="note-list">'
        f'<caption class="sb-sr-only">{escape(t("notes.listCaption"))}</caption><tbody>{rows}</tbody></table>'
        f'<p class="sb-table-filter__empty" role="status" hidden>{escape(t("notes.filterEmpty"))}</p></div>'
    )


def empty(t: Translator) -> str:
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon" aria-hidden="true">{note_glyph("36")}</div>'
        f'<p class="sb-empty__title">{escape(t("notes.emptyTitle"))}</p>'
        f'<p class="sb-empty__text">{escape(t("notes.emptyText"))}</p></div>'
    )


def flyout(notes: list[Note], epochs: dict[str, int], now: float, error: str, t: Translator) -> str:
    """Header, quick form, filterable list (or the empty card), and the editors."""
    parts = [header(len(notes), t)]
    if error:
        parts.append(alert(error))
    parts.append(quick_form(f"draft-{epochs['draft']}", t))
    if notes:
        parts.append(note_table(notes, now, t))
        parts.extend(
            editor(
                f"edit-{token(note.id)}",
                t("notes.editTitle"),
                f"edit-{token(note.id)}",
                note.text,
                f"save:{note.id}",
                t,
            )
            for note in notes
        )
    else:
        parts.append(empty(t))
    parts.append(editor("compose", t("notes.newTitle"), f"compose-{epochs['compose']}", "", "compose", t))
    return "".join(parts)


def toast_saved(note: Note, t: Translator) -> str:
    return (
        f'<div class="sb-row">{icon("check", "sb-ok")}<span class="sb-wrap"><strong>{escape(t("notes.saved"))}</strong>'
        f" · {escape(clip(name(note, t), TITLE_CHARS))}</span></div>"
    )


def toast_deleted(note: Note, t: Translator) -> str:
    return (
        f'<div class="sb-row">{icon("trash-2")}<span class="sb-wrap"><strong>{escape(t("notes.deleted"))}</strong>'
        f" · {escape(clip(name(note, t), TITLE_CHARS))}</span>"
        f'<button type="button" class="sb-btn sb-btn--sm sb-push" data-action="undo">{icon("rotate-cw")}{escape(t("notes.undo"))}</button></div>'
    )
