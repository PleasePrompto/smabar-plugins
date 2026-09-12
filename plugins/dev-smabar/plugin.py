# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""dev-smabar — a live catalogue of the smabar plugin UI kit.

One tile whose flyout walks through every sb-* class, every kit convention
(icons, charts, badges, marquee, rotator, clock, tabs, carousel, tooltips,
context menus) and the three native interaction patterns a plugin can use
without shipping a line of JavaScript: <details>, <dialog> + command invokers
and [popover].

The tile stays one calm line; the showcase lives in the flyout, which is about
340 px wide — so the sections are collapsed <details> rows and the whole table
of contents fits on one screen.

The flyout is rendered ONCE (plus on a settings change). Every button in it
answers with a `popup` render instead of a re-render, because a re-render
would collapse the accordion section the user just opened.
"""

import html
import os
import re
import urllib.parse
from typing import Any

import kit_sections as ks
from smabar_sdk import Plugin

app = Plugin()

TILE = "kit"

#: The carousel / media images, generated once into app.data_dir.
SLIDES = (
    ("slide-1.svg", "#a78bfa", "#f472b6", "sb-asset:"),
    ("slide-2.svg", "#38bdf8", "#34d399", "generated"),
    ("slide-3.svg", "#fbbf24", "#fb7185", "locally"),
)

TOASTS = {
    "ok": ("Saved", 'A popup with target="popup" and a 6 s ttl.'),
    "info": ("Dev Kit", "This whole flyout is one plugin, zero JavaScript."),
    "warn": ("Careful", "Popups have no rate limit — you own the frequency."),
    "danger": ("Failed", "Nothing actually broke. This is the danger flavour."),
}

state: dict[str, Any] = {"data_uri": "", "classes": 0}


def esc(text: object) -> str:
    return html.escape(str(text))


# --------------------------------------------------------------------------
# generated assets
# --------------------------------------------------------------------------


def slide_svg(top: str, bottom: str, caption: str) -> str:
    """A standalone SVG file — loaded through <img>, so it is not sanitized."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" '
        'width="320" height="180">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{top}"/>'
        f'<stop offset="1" stop-color="{bottom}"/>'
        "</linearGradient></defs>"
        '<rect width="320" height="180" fill="url(#g)"/>'
        '<text x="26" y="106" font-family="system-ui, sans-serif" '
        f'font-size="30" font-weight="700" fill="#111317">{caption}</text>'
        "</svg>"
    )


def write_assets() -> None:
    """Write the slide images atomically; data_dir writes never reload us."""
    for name, top, bottom, caption in SLIDES:
        target = os.path.join(str(app.data_dir), name)
        tmp = f"{target}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(slide_svg(top, bottom, caption))
            os.replace(tmp, target)
        except OSError as error:
            app.log(
                "warn", "could not write a slide image", file=name, error=str(error)
            )


def data_uri() -> str:
    svg = slide_svg("#22c1a7", "#3b82f6", "data: URI")
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def count_kit_classes(markup: str) -> int:
    """How many distinct sb-* classes this page actually exercises."""
    found: set[str] = set()
    for group in re.findall(r'class="([^"]*)"', markup):
        found.update(name for name in group.split() if name.startswith("sb-"))
    return len(found)


def tile_html() -> str:
    return (
        '<div class="sb-tile" data-badge="12" title="The smabar plugin UI kit,'
        ' end to end">'
        '<span data-rotator="up" data-rotator-interval="3500">'
        '<span class="sb-inline">'
        '<span data-lucide="layout-grid" aria-hidden="true"></span>'
        "<span>UI Kit</span></span>"
        '<span class="sb-inline">'
        '<span data-lucide="sparkles" aria-hidden="true"></span>'
        f'<span class="sb-mono">{state["classes"]}</span><span>classes</span>'
        "</span>"
        '<span class="sb-inline">'
        '<span data-lucide="layers" aria-hidden="true"></span>'
        f'<span class="sb-mono">{len(ks.SECTIONS)}</span><span>sections</span>'
        "</span></span></div>"
    )


def hover_html() -> str:
    return (
        '<div class="sb-row">'
        '<span class="sb-icon-badge">'
        '<span data-lucide="layout-grid" aria-hidden="true"></span></span>'
        "<span>UI kit showcase</span>"
        f'<span class="sb-badge sb-badge-accent sb-push">{len(ks.SECTIONS)}</span>'
        "</div>"
        '<p class="sb-meta">Click to open the catalogue.</p>'
    )


def compact() -> bool:
    return str(app.settings.get("density", "comfortable")) == "compact"


def render() -> None:
    # Built twice: the hero prints the class count, and the only honest source
    # for that number is the finished page itself.
    draft = ks.flyout(state["data_uri"], 0, compact())
    state["classes"] = count_kit_classes(draft + tile_html() + hover_html())
    app.render(
        TILE, "flyout", ks.flyout(state["data_uri"], state["classes"], compact())
    )
    app.render(TILE, "tile", tile_html())
    app.render(TILE, "hover", hover_html())


def popup(flavor: str, title: str, body: str, ttl: int | None = 6000) -> None:
    app.render(
        TILE,
        "popup",
        f'<div class="sb-toast sb-toast--{esc(flavor)}"><div>'
        f'<div class="sb-toast__title">{esc(title)}</div>'
        f'<div class="sb-toast__text">{body}</div></div></div>',
        ttl,
    )


def fields_table(value: object) -> str:
    """What the shell collected from every [data-field] in the tile."""
    if not isinstance(value, dict) or not value:
        return "No fields were sent."
    rows = "".join(
        f'<div class="sb-row"><span class="sb-muted">{esc(key)}</span>'
        f'<span class="sb-mono sb-push">{esc(entry) or "—"}</span></div>'
        for key, entry in sorted(value.items())
    )
    return f'<div class="sb-list">{rows}</div>'


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------


@app.on_ready
def ready() -> None:
    write_assets()
    state["data_uri"] = data_uri()
    render()
    app.log(
        "info", "dev kit ready", sections=len(ks.SECTIONS), classes=state["classes"]
    )


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    render()


@app.on_action(TILE)
def handle(action: str, value: object) -> None:
    """One handler for every button, menu entry and context-menu selection.

    Nothing here re-renders the flyout: the answer is always a popup, so the
    accordion section the user opened stays open.
    """
    if action == "tile":
        # The shell sends this on every tile click, next to opening the
        # flyout. Nothing to do — but it is not an unknown action either.
        return
    if action == "toast":
        flavor = str(value) if str(value) in TOASTS else "info"
        title, body = TOASTS[flavor]
        popup(flavor, title, esc(body))
        return
    if action == "about":
        popup(
            "info",
            "Dev Kit",
            "A Python process that emits HTML strings. Every element you see "
            "is a kit class the shell styles inside a shadow root.",
            None,
        )
        return
    if action == "menu":
        popup("info", "Menu entry", f"You picked <code>{esc(value)}</code>.")
        return
    if action == "ctx":
        popup(
            "ok",
            "Right-click menu",
            f"Arrived as a normal action: <code>{esc(value)}</code>.",
        )
        return
    if action == "echo":
        popup("ok", "Your fields", fields_table(value))
        return
    app.log("warn", "unknown action", action=action)


if __name__ == "__main__":
    app.run()
