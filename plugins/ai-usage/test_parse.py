# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the two parsers. Run: python3 test_parse.py"""

import json
import sys
import tempfile
import types
from pathlib import Path


class _StubPlugin:
    """Enough of the SDK surface to import plugin.py without a running bar."""

    settings: dict = {}
    data_dir = Path(tempfile.gettempdir())

    def every(self, *_args):
        return lambda fn: fn

    def on_action(self, *_args):
        return lambda fn: fn

    def on_ready(self, fn):
        return fn

    def on_settings_changed(self, fn):
        return fn

    def log(self, *_args, **_kwargs):
        pass

    rendered: dict = {}

    def render(self, _tile, target, html, **_kwargs):
        self.rendered[target] = html

    def run(self):
        pass


sys.modules["smabar_sdk"] = types.SimpleNamespace(Plugin=_StubPlugin)
sys.path.insert(0, str(Path(__file__).parent))
import plugin  # noqa: E402

# One real `claude /usage` screen after ANSI stripping: cursor jumps glue words
# together and the "+50% promo" line sits between two quota blocks.
SCREEN = (
    "Opus 5 · Claude Max · hello@example.com\n"
    "Current session███       13%usedResets 8:30pm(Europe/Berlin)"
    "Current week (all models)███ 51%usedResets Aug 26, 3pm(Europe/Berlin)"
    "+50% weekly limits promo through Aug 31 · clau.de/cc-50-promo"
    "Current week (Fable)███ 85%usedResets Aug 26, 3pm(Europe/Berlin)"
)
# The screen redraws, so the buffer holds several frames — the newest must win.
FRAMES = SCREEN + SCREEN.replace("13%", "22%")

limits, plan = plugin.parse_claude(FRAMES)
assert plan == "Max", plan
assert [item["label"] for item in limits] == ["Session", "Week", "Week · Fable"], limits
assert [item["pct"] for item in limits] == [22, 51, 85], limits
assert limits[0]["reset"] == "8:30pm", limits[0]
assert limits[1]["reset"] == "Aug 26, 3pm", limits[1]

# A half-drawn trailing frame must not shadow the last complete one.
assert plugin.parse_claude(SCREEN + "Current session")[0][0]["pct"] == 13

# No quota block at all → no limits, and the caller decides what to report.
assert plugin.parse_claude("Loading usage data…") == ([], "")

# Regression: the TUI positions text with cursor jumps, so a frame can arrive
# with every space missing. Both spellings must parse, and labels get re-spaced.
GLUED = (
    "Currentsession███13%usedResets8:30pm(Europe/Berlin)"
    "Currentweek(allmodels)███ 51%usedResetsAug26,3pm(Europe/Berlin)"
    "Currentweek(Fable)███ 85%usedResetsAug26,3pm(Europe/Berlin)"
)
glued, _plan = plugin.parse_claude(GLUED)
assert [item["label"] for item in glued] == ["Session", "Week", "Week · Fable"], glued
assert [item["pct"] for item in glued] == [13, 51, 85], glued
assert glued[1]["reset"] == "Aug 26, 3pm", glued[1]
assert glued[0]["reset"] == "8:30pm", glued[0]

# Regression: the TUI drops a character now and then ("Reses 10am") — keep the time.
dropped, _plan = plugin.parse_claude("Current session███ 7%usedReses10am (Europe/Berlin)")
assert dropped[0]["reset"] == "10am", dropped

assert plugin.tidy("  Aug26,3pm ") == "Aug 26, 3pm"
assert plugin.tidy("Aug 26, 3pm") == "Aug 26, 3pm"
assert plugin.tidy("") == ""

assert plugin.window_label(10080) == "7-day"
assert plugin.window_label(300) == "5-hour"
assert plugin.window_label(None) == "Usage"
assert plugin.window_label(0) == "Usage"

assert plugin.status_class(0) == ""
assert plugin.status_class(60) == "sb-warn"
assert plugin.status_class(85) == "sb-crit"
assert plugin.worst([]) is None
assert plugin.worst([{"pct": 3}, {"pct": 9}])["pct"] == 9

# Only installed agents render, Claude above Codex; every state keeps the tile's shape.
out = plugin.app.rendered
plugin.state["installed"] = []
plugin.render_all()
assert "–" in out["tile"] and plugin.NONE_INSTALLED in out["flyout"], out["tile"]
plugin.state["installed"] = ["codex"]
plugin.render_all()
assert "Claude" not in out["tile"] and "Claude" not in out["flyout"] and "Codex" in out["tile"]
plugin.state["claude"].update({"limits": limits, "plan": "Max 20×", "error": "", "at": "10:00"})
plugin.state["installed"] = ["claude", "codex"]
plugin.render_all()
assert out["flyout"].index('aria-label="Claude"') < out["flyout"].index('aria-label="Codex"')
assert "Max 20×" in out["flyout"] and "85%" in out["tile"] and "sb-crit" in out["tile"]
assert "data-tab" not in out["flyout"] and out["flyout"].count("<article") == 2
assert "--sb-accent: #d97757" in out["flyout"] and "--sb-accent: #10a37f" in out["flyout"]


# Windows transport: pywinpty hands console output over on a local socket, so the
# select()-based read must answer b"" on silence, the bytes on data and None at EOF.
import socket  # noqa: E402


class _FakePtyProcess:
    def __init__(self, sock):
        self.fileobj = sock

    def read(self, size):
        data = self.fileobj.recv(size)
        if not data:
            raise EOFError("Pty is closed")
        return data.decode("utf-8")


near, far = socket.socketpair()
term = plugin.WindowsTerminal.__new__(plugin.WindowsTerminal)
term.proc = _FakePtyProcess(near)
assert term.read(0.05) == b""
far.sendall("Current session 7%used".encode("utf-8"))
assert term.read(0.5) == b"Current session 7%used"
far.close()
assert term.read(0.5) is None
near.close()

# Codex: the newest rate_limits line of a rollout tail wins, junk lines are skipped.
def rollout_line(stamp: str, pct: float) -> str:
    return json.dumps(
        {
            "timestamp": stamp,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "rate_limits": {
                    "primary": {"used_percent": pct, "window_minutes": 10080, "resets_at": 0},
                    "secondary": None,
                    "plan_type": "prolite",
                },
            },
        }
    )


with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
    handle.write(rollout_line("2026-08-22T10:00:00.000Z", 12.0) + "\n")
    handle.write('{"broken json\n')
    handle.write('{"type":"turn","payload":{}}\n')
    handle.write(rollout_line("2026-08-22T14:57:34.684Z", 59.0) + "\n")
    path = handle.name

stamp, limits = plugin.tail_rate_limits(path)
assert stamp.startswith("2026-08-22T14:57"), stamp
assert limits["primary"]["used_percent"] == 59.0, limits
assert plugin.tail_rate_limits(path + ".missing") is None
Path(path).unlink()

print("ok")
