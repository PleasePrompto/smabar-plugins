# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the history store, the markup helpers and the clipboard watcher.

Run: python3 test_history.py. On an X11 desktop with xsel the watcher check copies one
line through the real clipboard and restores what was there before.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import views  # noqa: E402
import watcher  # noqa: E402
from model import History  # noqa: E402

HERE = Path(__file__).parent
EN = json.loads((HERE / "locales/en.json").read_text(encoding="utf-8"))
DE = json.loads((HERE / "locales/de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)


def t(key: str) -> str:
    return EN.get(key, key)


def texts(entries: list[dict]) -> list[str]:
    return [entry["text"] for entry in entries]


with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "history.json"
    history = History(path)
    try:
        history.load()
        raise AssertionError("a missing file must raise FileNotFoundError")
    except FileNotFoundError:
        pass

    limits = {"max_chars": 50, "max_entries": 3}
    # Ignore rules: whitespace-only and oversized text never enter the history.
    assert history.add("  \n\t ", 1, **limits) is False
    assert history.add("x" * 51, 1, **limits) is False
    assert history.entries == []

    assert history.add("alpha", 1, **limits) is True
    assert history.add("alpha", 2, **limits) is False, "the text on top is not a change"
    assert history.add("beta", 3, **limits) and history.add("gamma", 4, **limits)
    alpha_id = history.entries[-1]["id"]
    # A repeat moves to the top, keeps its id and gets the new time.
    assert history.add("alpha", 5, **limits) is True
    assert texts(history.entries) == ["alpha", "gamma", "beta"]
    assert history.entries[0]["id"] == alpha_id and history.entries[0]["at"] == 5

    # The limit counts unpinned entries only and drops the oldest of them.
    beta_id = history.entries[2]["id"]
    assert history.pin(beta_id, True) is True
    assert history.pin(beta_id, True) is False, "pinning twice is not a change"
    assert history.add("delta", 6, **limits) is True
    assert texts(history.entries) == ["delta", "alpha", "gamma", "beta"]
    assert history.add("epsilon", 7, **limits) is True
    assert texts(history.entries) == ["epsilon", "delta", "alpha", "beta"]
    assert texts(history.ordered()) == ["beta", "epsilon", "delta", "alpha"]
    assert history.unpinned() == 3

    # Search: case-insensitive substring in display order, with a limit.
    assert texts(history.search("a", 10)) == ["beta", "delta", "alpha"]
    assert texts(history.search("ALPHA", 10)) == ["alpha"]
    assert texts(history.search("a", 1)) == ["beta"]
    assert history.search("zzz", 10) == []

    # Save is atomic (no .tmp left behind) and round-trips.
    history.save()
    assert not path.with_suffix(".tmp").exists()
    reloaded = History(path)
    reloaded.load()
    assert reloaded.entries == history.entries

    assert history.delete("nope") is False
    assert history.delete(alpha_id) is True
    assert history.clear() == 2, "clear removes the unpinned entries only"
    assert texts(history.entries) == ["beta"]
    assert history.clear() == 0

    # A smaller limit trims immediately; pins stay however many there are.
    for index in range(3):
        history.add(f"loose {index}", 10 + index, **limits)
    assert history.trim(1) is True and texts(history.entries) == ["loose 2", "beta"]
    for index in range(5):
        history.add(f"pin {index}", 20 + index, **limits)
        history.pin(history.entries[0]["id"], True)
    assert history.trim(1) is False and len(history.entries) == 7

    # A malformed file is an error the plugin reports, not a crash or silent reset.
    for broken in ("{}", "[1, 2]", '{"entries": [{"id": 1}]}'):
        path.write_text(broken, encoding="utf-8")
        try:
            History(path).load()
            raise AssertionError(f"{broken!r} must not load")
        except ValueError:
            pass

# Markup helpers.
assert views.one_line("a\n\n b   c", 100) == "a b c"
assert views.one_line("abcdefghij", 5) == "abcd…"
for code in (
    "https://example.com/x?y=1",
    "#38bdf8",
    "git status --short",
    "$ ls -la",
    "const x = () => 1;",
    "    indented();",
):
    assert views.looks_like_code(code), code
assert not views.looks_like_code("Meeting moved to Thursday, bring the slides.")
assert views.relative_time(0, 30, t) == "just now"
assert views.relative_time(0, 90, t) == "1 min ago"
assert views.relative_time(0, 7200, t) == "2 h ago"
assert views.relative_time(0, 3 * 86400, t) == "3 d ago"
assert views.relative_time(0, 30 * 86400, t) == "1970-01-01"

NOW = 1_000_000
entries = [
    {"id": "a1", "text": "line one\nline two\nline three", "at": NOW - 120, "pinned": True},
    {"id": "b2", "text": "https://smabar.com/docs", "at": NOW - 5, "pinned": False},
]
html = views.flyout(entries, 1, False, "", "", NOW, t)
assert 'data-sb-copy-text="line one\nline two\nline three"' in html, "copy carries the full text"
assert "3 lines · 28 chars" in html and "2 min ago" in html
assert views.size_note("x" * 60, t) == "60 chars" and views.size_note("short", t) == ""
assert 'aria-pressed="true"' in html and html.count('data-lucide="pin"') == 3, "pinned rows carry a pin glyph"
assert html.count('data-action="pin"') == 2 and html.count('data-action="delete"') == 2
assert 'data-value="{&quot;id&quot;:&quot;a1&quot;,&quot;pinned&quot;:false}"' in html, "pinned entry unpins"
assert 'class="sb-wrap sb-mono"' in html and 'data-sb-filter="#clip-list"' in html
assert '<dialog class="sb-modal sb-modal--sm" id="clip-clear"' in html and "clip." not in html
assert 'aria-label="Pause recording"' in html and "Removes 1 unpinned entries" in html
assert "Paused" in views.flyout(entries, 1, True, "", "", NOW, t)

empty = views.flyout([], 0, False, "", "", NOW, t)
assert "sb-empty" in empty and "data-sb-filter" not in empty and " disabled" in empty
assert "Install xclip" in views.flyout([], 0, False, "Install xclip", "", NOW, t)

# The render budget: rows past ~700 KB are left out and counted.
big = [{"id": str(i), "text": "x" * 300_000, "at": NOW, "pinned": False} for i in range(3)]
capped = views.flyout(big, 3, False, "", "", NOW, t)
assert capped.count('data-action="delete"') == 2 and "1 older entries are not shown" in capped

tile_html = views.tile("first line\nsecond line of the copied text", False, "", t)
assert tile_html.startswith('<div class="sb-tile"><svg '), "the glyph leads the tile in every state"
assert tile_html.endswith('<span>first line second line of t…</span></div>')
for state in (views.tile(None, False, "", t), views.tile("x", True, "", t), views.tile("x", False, "xclip", t)):
    assert state.startswith('<div class="sb-tile"><svg '), state
assert "Paused" in views.tile("x", True, "", t) and "Empty" in views.tile(None, False, "", t)
assert "Install wl-clipboard" in views.tile("x", False, "wl-clipboard", t)
hover = views.hover(entries, False, NOW, t)
assert hover.count("sb-row") == 2 and "just now" in hover and 'data-lucide="pin"' in hover
assert "Empty" in views.hover([], False, NOW, t)

# --- watcher: never reads the clipboard itself, signals on a real change (X11 with xsel only) ---
if sys.platform == "linux":
    env = dict(os.environ)
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    assert watcher.start(lambda: None, lambda reason: None) == ""  # nothing to watch, no thread
    os.environ.clear()
    os.environ.update(env)
if sys.platform == "linux" and os.environ.get("DISPLAY") and shutil.which("xsel"):
    seen = threading.Event()
    assert watcher.start(seen.set, lambda reason: None) == "XFixes"
    before = subprocess.run(["xsel", "--clipboard", "--output"], capture_output=True).stdout
    subprocess.run(["xsel", "--clipboard", "--input"], input=b"clipboard-history watcher check", check=True)
    assert seen.wait(2.0), "no XFixes event within 2 s"
    subprocess.run(["xsel", "--clipboard", "--input"], input=before, check=True)
    time.sleep(0.3)  # let the running plugin, if any, read the restored text before the test ends

print("ok")
