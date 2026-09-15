# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the note store, the markup and the plugin's state machine.

Run: python3 test_notes.py (no bar needed; everything happens in a temp folder).
"""

import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import views
from model import MAX_TEXT, NoteError, NoteStore, preview_of, title_of

EN = json.loads((HERE / "locales/en.json").read_text(encoding="utf-8"))
DE = json.loads((HERE / "locales/de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)
t = EN.__getitem__  # a key missing from the locale fails loudly


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 1.0) -> None:
        self.now += seconds


# --- titles and previews from Markdown ---------------------------------------
assert title_of("# Shopping list\n- Milk\n- Eggs") == "Shopping list"
assert preview_of("# Shopping list\n- Milk\n- Eggs") == "Milk Eggs"
assert title_of("\n\n  hello   world  \n") == "hello world"
assert title_of("- [ ] call Anna") == "call Anna"
assert title_of("3. third point") == "third point"
assert title_of("> quoted thought") == "quoted thought"
assert title_of("x" * 100) == "x" * 79 + "…"
assert title_of("   \n\n") == ""
assert preview_of("only a title") == ""

# --- the store ----------------------------------------------------------------
tmp = tempfile.TemporaryDirectory()
clock = Clock()
store = NoteStore(Path(tmp.name), now=clock)
store.load()
assert store.notes() == [] and store.rescan() is False

a = store.add("# Shopping list\n- Milk\n- Eggs")
clock.tick()
b = store.add("Meeting idea\r\nTalk about the roadmap")
clock.tick()
c = store.add("https://example.com/docs")
clock.tick()
assert (store.root / f"{a.id}.md").read_text(encoding="utf-8") == "# Shopping list\n- Milk\n- Eggs\n"
assert b.text == "Meeting idea\nTalk about the roadmap"
assert [n.id for n in store.notes()] == [c.id, b.id, a.id], "newest first"
assert a.title == "Shopping list" and a.preview == "Milk Eggs"

# Pinned first; pinning another note replaces the pin; None unpins.
store.pin(b.id)
assert [n.id for n in store.notes()] == [b.id, c.id, a.id]
assert store.get(b.id).pinned and not store.get(c.id).pinned
store.pin(a.id)
assert [n.id for n in store.notes()] == [a.id, c.id, b.id]
store.pin(None)
assert [n.id for n in store.notes()] == [c.id, b.id, a.id]
assert json.loads((Path(tmp.name) / "pinned.json").read_text(encoding="utf-8"))["pinned"] is None

# Update keeps the id, bumps "updated" and moves the note to the top.
clock.tick()
changed = store.update(a.id, "Shopping list\nBread")
assert changed.id == a.id and changed.updated > c.updated
assert next(n.id for n in store.notes()) == a.id
assert store.get(a.id).text == "Shopping list\nBread"

# Delete returns the note with its pin state; restore brings both back.
store.pin(b.id)
gone = store.delete(b.id)
assert gone.pinned and gone.text == b.text
assert not (store.root / f"{b.id}.md").exists() and store.pinned_id is None
assert [n.id for n in store.notes()] == [a.id, c.id]
clock.tick()
back = store.restore(gone)
assert back.id == b.id and back.pinned and store.pinned_id == b.id
assert (store.root / f"{b.id}.md").exists()
assert next(n.id for n in store.notes()) == b.id

# Search is case-insensitive over the whole text.
assert [n.id for n in store.notes("ROADMAP")] == [b.id]
assert [n.id for n in store.notes("bread")] == [a.id]
assert store.notes("nothing like this") == []

# Validation names the locale key the UI shows.
for bad, key in (("", "empty"), ("  \n ", "empty"), ("x" * (MAX_TEXT + 1), "long")):
    try:
        store.add(bad)
        raise AssertionError(f"accepted {key}")
    except NoteError as exc:
        assert exc.key == key, exc.key
try:
    store.get("nope")
    raise AssertionError("missing note accepted")
except NoteError as exc:
    assert exc.key == "missing"

# Rescan picks up files another editor writes, edits and removes.
external = store.root / "From Obsidian.md"
external.write_text("Obsidian note\nwritten outside\n", encoding="utf-8")
assert store.rescan() is True
assert store.get("From Obsidian").title == "Obsidian note"
assert store.rescan() is False
external.write_text("Obsidian note\nedited outside, longer now\n", encoding="utf-8")
assert store.rescan() is True and "edited" in store.get("From Obsidian").text
store.pin("From Obsidian")
external.unlink()
assert store.rescan() is True and store.pinned_id is None
try:
    store.get("From Obsidian")
    raise AssertionError("removed file still listed")
except NoteError:
    pass

# --- markup -------------------------------------------------------------------
store.pin(a.id)
notes = store.notes()
NOW = clock.now
assert views.tile_label(notes, "pinned", t) == "Shopping list"
assert views.tile_label(notes, "latest", t) == "Meeting idea"
assert views.tile_label(notes, "count", t) == "3 notes"
assert views.tile_label(notes[:1], "count", t) == "1 note"
assert views.tile_label([], "pinned", t) == "No notes yet"
for state in (views.tile(notes, "pinned", t), views.tile(notes, "count", t), views.tile([], "latest", t)):
    assert state.startswith('<div class="sb-tile"><svg') and 'width="1em"' in state, "glyph first in every tile state"
assert views.clip("a" * 30, 24) == "a" * 23 + "…"
assert views.when(NOW - 5, NOW, t) == "just now"
assert views.when(NOW - 130, NOW, t) == "2 min ago"
assert views.when(NOW - 7200, NOW, t) == "2 h ago"
assert views.when(NOW - 3 * 86400, NOW, t) == "3 d ago"
assert views.when(NOW - 30 * 86400, NOW, t).count("-") == 2, "a date after a week"
assert views.token("From Obsidian") != views.token("From-Obsidian") and " " not in views.token("a b")

html = views.flyout(notes, {"draft": 2, "compose": 0}, NOW, "", t)
assert 'data-field="draft-2"' in html and 'data-field="compose-0"' in html
assert 'id="note-list"' in html and html.count("<tr>") == 3 and html.count("<dialog") == 4
assert f'data-action="save:{a.id}"' in html and f'data-action="pin:{a.id}"' in html
assert html.index(f"delete:{a.id}") < html.index(f"delete:{b.id}"), "pinned note first"
assert "notes." not in html, "every visible string is translated"
assert "<script" not in html
empty = views.flyout([], {"draft": 0, "compose": 0}, NOW, "Boom", t)
assert "sb-empty" in empty and "Boom" in empty and "note-list" not in empty
hover = views.hover(notes[0], t)
assert "Shopping list" in hover and "Bread" in hover
assert "No notes yet" in views.hover(None, t)
evil = store.add("<b>x</b> & y")
escaped = views.flyout(store.notes(), {"draft": 0, "compose": 0}, NOW, "", t)
assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in escaped and "<b>x" not in escaped
store.delete(evil.id)

# --- the plugin's state machine, with a stub SDK -------------------------------


class _Popups:
    def __init__(self) -> None:
        self.shown: list = []

    def show(self, _tile, popup_id, _html, ttl_ms=None, sound=None):
        self.shown.append((popup_id, ttl_ms))

    def dismiss(self, _tile, popup_id):
        self.shown.append((popup_id, "dismissed"))


class _StubPlugin:
    """Enough of the SDK surface to import plugin.py without a running bar."""

    def __init__(self) -> None:
        self.settings: dict = {}
        self.data_dir = Path(tempfile.mkdtemp())
        self.rendered: dict = {}
        self.logged: list = []
        self.popups = _Popups()

    def every(self, *_args):
        return lambda fn: fn

    def on_action(self, *_args):
        return lambda fn: fn

    def on_ready(self, fn):
        return fn

    def on_settings_changed(self, fn):
        return fn

    def command(self, *_args, **_kwargs):
        return lambda fn: fn

    def log(self, level, message, **_fields):
        self.logged.append((level, message))

    def render(self, _tile, target, html, **_kwargs):
        self.rendered[target] = html

    def t(self, key):
        return EN[key]

    def run(self):
        pass


sys.modules["smabar_sdk"] = types.SimpleNamespace(Plugin=_StubPlugin)
import plugin

out = plugin.app.rendered
plugin.ready()
assert "No notes yet" in out["tile"] and "sb-empty" in out["flyout"]

plugin.on_action("add", {"draft-0": "Buy stamps\nand envelopes"})
assert plugin.epochs["draft"] == 1 and "Buy stamps" in out["tile"]
assert plugin.app.popups.shown[-1] == ("saved", plugin.TOAST_MS)
first = plugin.db().notes()[0].id
plugin.on_action("compose", {"compose-0": "Second note"})
assert plugin.epochs == {"draft": 1, "compose": 1}
plugin.on_action(f"pin:{first}", None)
assert plugin.db().pinned_id == first and "Buy stamps" in out["tile"]

plugin.app.settings = {"tileMode": "count"}
plugin.settings_changed(plugin.app.settings)
assert "2 notes" in out["tile"]
plugin.app.settings = {"tileMode": "latest"}
plugin.render()
assert "Second note" in out["tile"]
plugin.app.settings = {"tileMode": "sideways"}
plugin.render()
assert plugin.app.logged[-1][0] == "warn" and "Buy stamps" in out["tile"], "bad setting falls back"
plugin.app.settings = {}

plugin.on_action(f"save:{first}", {f"edit-{views.token(first)}": "Buy stamps\nand a pen"})
assert "a pen" in plugin.db().get(first).text
plugin.on_action("add", {"draft-1": "   "})
assert plugin.error == EN["notes.error.empty"] and "sb-alert" in out["flyout"]
assert plugin.epochs["draft"] == 1, "a rejected draft keeps its field name"
plugin.on_action(f"pin:{first}", None)
assert plugin.error == "" and plugin.db().pinned_id is None
plugin.on_action(f"pin:{first}", None)

plugin.on_action(f"delete:{first}", None)
assert plugin.last_deleted is not None and plugin.last_deleted.id == first
assert plugin.app.popups.shown[-1] == ("deleted", plugin.UNDO_MS) and len(plugin.db().notes()) == 1
plugin.on_action("undo", None)
assert plugin.last_deleted is None and len(plugin.db().notes()) == 2 and plugin.db().get(first).pinned
assert plugin.app.popups.shown[-1] == ("deleted", "dismissed")
plugin.on_action("undo", None)
assert plugin.error == EN["notes.error.missing"]

# Agent commands validate their input and return the documented shapes.
added = plugin.cmd_add({"text": "From an agent\nwith a body"})
assert added["title"] == "From an agent"
assert plugin.cmd_search({"query": "AGENT"})["notes"][0]["id"] == added["id"]
listed = plugin.cmd_list({"limit": 2})["notes"]
assert len(listed) == 2 and listed[0]["id"] == first, "pinned first, then limit"
got = plugin.cmd_get({"id": added["id"]})
assert got["text"] == "From an agent\nwith a body" and got["updated"].count(":") >= 2
assert plugin.cmd_delete({"id": added["id"]}) == {"deletedId": added["id"]}
for call in (
    lambda: plugin.cmd_list({"limit": 0}),
    lambda: plugin.cmd_get({"id": 5}),
    lambda: plugin.cmd_get({"id": "nope"}),
    lambda: plugin.cmd_add({"text": ""}),
    lambda: plugin.cmd_search({"query": "x" * 201}),
):
    try:
        call()
        raise AssertionError("invalid command arguments accepted")
    except ValueError:
        pass

# The timer only renders when the folder changed.
(plugin.app.data_dir / "notes" / "dropped in.md").write_text("Dropped in\nby hand\n", encoding="utf-8")
plugin.app.settings = {"tileMode": "count"}
plugin.tick()
assert "3 notes" in out["tile"]

print("ok")
