# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the parser, the ring buffer, the state machine and the markup.
Run: python3 test_checks.py — no bar and no network needed."""

import json
import socket
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import checks  # noqa: E402
import views  # noqa: E402

# --- target parsing --------------------------------------------------------

site = checks.parse_target("https://smabar.com")
assert (site.kind, site.name, site.host, site.where) == ("http", "smabar.com", "smabar.com", "smabar.com"), site
api = checks.parse_target(" API | https://api.example.com/health?x=1 ")
assert (api.name, api.spec, api.host) == ("API", "https://api.example.com/health?x=1", "api.example.com"), api
db = checks.parse_target("tcp://db.internal:5432")
assert (db.kind, db.name, db.host, db.port, db.where) == ("tcp", "db.internal:5432", "db.internal", 5432, "db.internal:5432"), db
router = checks.parse_target("Router | ping:192.168.0.1")
assert (router.kind, router.name, router.host, router.port) == ("ping", "Router", "192.168.0.1", 0), router
assert checks.parse_target("HTTP://Example.com").kind == "http"
assert checks.parse_target("Plain | http://localhost:8080").host == "localhost"

for bad in ("ftp://x", "example.com", "tcp://host", "tcp://host:abc", "tcp://:80", "ping:", "ping:a b", "Name |", ""):
    try:
        checks.parse_target(bad)
    except checks.TargetError as error:
        assert error.code == "invalid" and error.entry == bad, (bad, error)
    else:
        raise AssertionError(f"{bad!r} was accepted")

targets, rejected = checks.parse_targets(
    ["https://a.example", "api | https://b.example", "API | https://c.example", "https://a.example", 42, "nope"]
)
assert [target.name for target in targets] == ["a.example", "api"], targets
assert [(error.code, error.entry) for error in rejected] == [
    ("duplicate", "API | https://c.example"),
    ("duplicate", "https://a.example"),
    ("invalid", "42"),
    ("invalid", "nope"),
], rejected
assert checks.parse_targets([]) == ([], [])

# --- failure codes -----------------------------------------------------------

assert checks.classify(socket.gaierror(-2, "Name or service not known")) == "dns"
assert checks.classify(TimeoutError("timed out")) == "timeout"
assert checks.classify(ConnectionRefusedError()) == "refused"
assert checks.classify(ssl.SSLCertVerificationError("bad cert")) == "tls"
assert checks.classify(ConnectionResetError()) == "error"
assert checks.classify("unknown host") == "error"

# --- ring buffer and uptime math ----------------------------------------------


def sample(t: int, ok: bool, ms: int = 100, code: str = "") -> dict:
    return {"t": t, "ok": ok, "ms": ms, "code": code or ("200" if ok else "timeout")}


entry = checks.new_entry()
for i in range(70):
    checks.apply(entry, sample(i, True, ms=i), history_size=60, threshold=2)
assert len(entry["history"]) == 60 and entry["history"][0]["ms"] == 10 and entry["history"][-1]["ms"] == 69

assert checks.uptime_percent([]) is None
assert checks.uptime_percent([sample(1, True), sample(2, True), sample(3, False), sample(4, True)]) == 75.0
assert checks.uptime_percent([sample(1, False)]) == 0.0
assert views.percent(None) == "–" and views.percent(100.0) == "100 %" and views.percent(99.83) == "99.8 %"
assert views.percent(98.0) == "98 %"

# --- state machine -------------------------------------------------------------

entry = checks.new_entry()
apply = lambda s: checks.apply(entry, s, history_size=10, threshold=2)  # noqa: E731
assert apply(sample(100, True)) is None and entry["status"] == "up" and entry["since"] == 100
assert apply(sample(160, False)) is None and entry["status"] == "up" and entry["fails"] == 1
assert apply(sample(220, False)) == "down" and entry["status"] == "down"
assert entry["since"] == 160, entry  # the outage starts with the first failure
assert apply(sample(280, False)) is None and entry["fails"] == 3
assert apply(sample(340, True)) == "up" and entry["since"] == 340 and entry["fails"] == 0
assert apply(sample(400, True)) is None

# From unknown, a failure streak still announces down; a success does not announce "back up".
entry = checks.new_entry()
assert apply(sample(1, False)) is None and entry["status"] == "unknown"
assert apply(sample(2, False)) == "down" and entry["since"] == 1
entry = checks.new_entry()
assert apply(sample(1, True)) is None and entry["status"] == "up"

# Threshold 1 flips on the first failure. A buffer shorter than the streak
# dates the outage from its oldest buffered failure.
entry = checks.new_entry()
assert checks.apply(entry, sample(5, False), history_size=5, threshold=1) == "down" and entry["since"] == 5
entry = checks.new_entry()
changes = [checks.apply(entry, sample(t, False), history_size=3, threshold=6) for t in range(1, 8)]
assert changes == [None] * 5 + ["down", None] and entry["since"] == 4 and entry["fails"] == 7, (changes, entry)

# --- persisted state ------------------------------------------------------------

assert checks.restore_entry(None) == checks.new_entry()
assert checks.restore_entry({"status": "sideways", "since": "x", "fails": -1, "history": "no"}) == checks.new_entry()
restored = checks.restore_entry(
    {"status": "down", "since": 160, "fails": 2, "history": [sample(100, True), {"t": "bad"}, sample(160, False)]}
)
assert restored == {"status": "down", "since": 160, "fails": 2, "history": [sample(100, True), sample(160, False)]}
assert json.loads(json.dumps(restored)) == restored

# --- markup ------------------------------------------------------------------------

strings = json.loads((Path(__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
german = json.loads((Path(__file__).parent / "locales" / "de.json").read_text(encoding="utf-8"))
assert set(strings) == set(german), set(strings) ^ set(german)
t = strings.__getitem__


def row(name: str, status: str, **extra: object) -> dict:
    base = {
        "name": name, "target": f"https://{name}", "host": name, "status": status, "latencyMs": 142,
        "uptimePercent": 99.8, "reason": "", "since": 1, "sinceSeconds": 240, "checks": 12,
        "points": [120, 150, 142],
    }
    return {**base, **extra}


assert "Add targets" in views.tile([], t) and "sb-muted" in views.tile([], t)
assert "Checking…" in views.tile([row("a", "unknown")], t)
# The brand mark comes first in every state, followed by the status icon.
for rows_ in ([], [row("a", "unknown")], [row("a", "up")], [row("a", "down")]):
    assert views.tile(rows_, t).count('data-lucide="activity"') == 1 and views.tile(rows_, t).count("data-lucide=") == 2
assert "2/2 up" in views.tile([row("a", "up"), row("b", "up")], t) and "sb-ok" in views.tile([row("a", "up")], t)
down_tile = views.tile([row("a", "up"), row("api", "down", reason="503", latencyMs=None)], t)
assert "1 down · api" in down_tile and "sb-crit" in down_tile, down_tile
assert "2 down · api, db" in views.tile([row("api", "down"), row("db", "down")], t)

hover = views.hover([row(f"t{i}", "up") for i in range(7)], t)
assert hover.count('class="sb-row"') == 5 and "+2 more" in hover, hover
assert "HTTP 503" in views.hover([row("api", "down", reason="503")], t)

flyout = views.flyout(
    [row("api", "down", reason="timeout", latencyMs=None, points=[])],
    problems=["x: use https://…"], next_iso="2026-09-15T12:00:00", checking=False,
    form_error="", epoch=3, interval=60, t=t,
)
assert "timeout · 4 min" in flyout and "data-sb-countdown" in flyout and "sb-alert--warn" in flyout, flyout
assert 'data-field="target-3"' in flyout and "data-chart" not in flyout
assert 'aria-label="Remove api"' in flyout and 'title="Remove api"' in flyout
spark_flyout = views.flyout([row("a", "up")], problems=[], next_iso="", checking=True,
                            form_error="Enter a target.", epoch=0, interval=60, t=t)
assert 'data-points="120,150,142"' in spark_flyout and "Checking…" in spark_flyout and "sb-error" in spark_flyout
assert "No targets yet" in views.flyout([], problems=[], next_iso="", checking=False, form_error="", epoch=0, interval=60, t=t)
assert "Back up: api after 4 min" in views.popup("up", views.tr(t, "uptime.popup.up", name="api", duration=views.duration(240, t)), t)
assert views.duration(59, t) == "59 s" and views.duration(3600, t) == "1 h" and views.duration(172800, t) == "2 d"
assert views.reason("503", t) == "HTTP 503" and views.reason("dns", t) == "DNS" and views.reason("weird", t) == "error"

print("ok")
