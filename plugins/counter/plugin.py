# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Counter: a number you bump from the flyout. Exercises actions and in-memory state."""

from smabar_sdk import Plugin

app = Plugin()

WIDGET = "counter"
REFRESH_SECONDS = 3600.0
state: dict = {"count": 0}


def render() -> None:
    count = state["count"]
    app.render(
        WIDGET,
        "tile",
        "<div class='sb-tile'><span data-lucide='hash' aria-hidden='true'></span>"
        f"<span class='sb-mono'>{count}</span></div>",
    )
    app.render(
        WIDGET,
        "flyout",
        "<div class='sb-header'>"
        "<span class='sb-icon-badge'><span data-lucide='hash' aria-hidden='true'></span></span>"
        "<span class='sb-title'>Counter</span>"
        "<div class='sb-header-actions'>"
        "<button class='sb-btn sb-btn-icon' data-action='increment' title='Add one'"
        " aria-label='Add one'><span data-lucide='plus' aria-hidden='true'></span></button>"
        "<button class='sb-btn sb-btn-icon' data-action='reset' title='Reset'"
        " aria-label='Reset'><span data-lucide='rotate-cw' aria-hidden='true'></span></button>"
        "</div></div>"
        f"<div class='sb-hero'><small>Count</small><h1>{count}</h1></div>",
    )


@app.every(REFRESH_SECONDS)
def refresh() -> None:
    # The first timer tick runs right after initialize, so it doubles as the initial render.
    render()


@app.on_action(WIDGET, "increment")
def increment(action: str, value: object) -> None:
    state["count"] += 1
    render()


@app.on_action(WIDGET, "reset")
def reset(action: str, value: object) -> None:
    state["count"] = 0
    render()


if __name__ == "__main__":
    app.run()
