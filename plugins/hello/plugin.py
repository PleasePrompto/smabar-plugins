# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Hello: greets whoever the settings name. The smallest complete smabar plugin."""

import html

from smabar_sdk import Plugin

app = Plugin()

WIDGET = "hello"
REFRESH_SECONDS = 60.0


def greeting() -> str:
    return html.escape(str(app.settings.get("name", "world")))


def render() -> None:
    name = greeting()
    app.render(
        WIDGET,
        "tile",
        "<div class='sb-tile'><span data-lucide='hand' aria-hidden='true'></span>"
        f"<span>Hello, {name}</span></div>",
    )
    app.render(
        WIDGET,
        "flyout",
        "<div class='sb-header'>"
        "<span class='sb-icon-badge'><span data-lucide='hand' aria-hidden='true'></span></span>"
        "<span class='sb-title'>Hello</span></div>"
        f"<div class='sb-hero'><small>Greeting</small><h1>Hello, {name}! 👋</h1></div>"
        "<p class='sb-meta'>Change the name in the widget settings.</p>",
    )


@app.every(REFRESH_SECONDS)
def refresh() -> None:
    # The first timer tick runs right after initialize, so it doubles as the initial render.
    render()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    render()


if __name__ == "__main__":
    app.run()
