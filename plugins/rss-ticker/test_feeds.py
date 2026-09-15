# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the feed parser, the refresh rules and the markup. Run: python3 test_feeds.py"""

import json
import sys
import tempfile
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import feeds  # noqa: E402
import views  # noqa: E402

NOW = int(datetime(2026, 9, 15, 12, 0).timestamp())  # local noon


def utc(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=UTC).timestamp())


RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>Example News</title>
<link>https://example.com/</link>
<item>
<title>First &amp; foremost</title>
<link>https://example.com/1</link>
<pubDate>Tue, 15 Sep 2026 08:30:00 GMT</pubDate>
<description><![CDATA[<p>Hello  <b>world</b> &amp; friends</p>]]></description>
</item>
<item>
<title>Undated item</title>
<link>https://example.com/2</link>
<description>Plain summary</description>
</item>
<item>
<link>https://example.com/no-title</link>
<pubDate>Tue, 15 Sep 2026 07:00:00 GMT</pubDate>
</item>
<item>
<title>Not a web link</title>
<link>mailto:someone@example.com</link>
</item>
<item>
<title>Long one</title>
<link>https://example.com/3</link>
<pubDate>Mon, 14 Sep 2026 20:00:00 +0200</pubDate>
<description>{"x" * 200}</description>
</item>
</channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Rust Blog</title>
<link rel="self" href="https://blog.example.org/feed.xml"/>
<entry>
<title type="html">Announcing Rust &lt;b&gt;1.99&lt;/b&gt;</title>
<link rel="self" href="https://blog.example.org/self"/>
<link rel="alternate" href="https://blog.example.org/1.99"/>
<updated>2026-09-15T12:00:00Z</updated>
<published>2026-09-15T09:15:00+02:00</published>
<summary>Short summary</summary>
</entry>
<entry>
<title>Only an enclosure link</title>
<link rel="enclosure" href="https://blog.example.org/audio.mp3"/>
<updated>2026-09-14T10:00:00Z</updated>
<content type="html">&lt;p&gt;Body text&lt;/p&gt;</content>
</entry>
</feed>
"""

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://rdf.example.net/">
<title>RDF Wire</title>
<link>https://rdf.example.net/</link>
<items><rdf:Seq><rdf:li rdf:resource="https://rdf.example.net/a"/></rdf:Seq></items>
</channel>
<item rdf:about="https://rdf.example.net/a">
<title>RDF headline</title>
<link>https://rdf.example.net/a</link>
<dc:date>2026-09-13T06:00:00+00:00</dc:date>
<description>Wire copy</description>
</item>
</rdf:RDF>
"""

# --- text and dates ------------------------------------------------------

assert feeds.clean_text("  a  <br/>b &amp; c ") == "a b & c"
assert feeds.clean_text("x" * 10, 5) == "xxxx…"
assert feeds.clean_text(None) == ""
assert feeds.parse_date("garbage", 7) == 7
assert feeds.parse_date("", 7) == 7
assert feeds.parse_date("Tue, 15 Sep 2026 08:30:00 -0000", 0) == utc(2026, 9, 15, 8, 30)  # naive → UTC
assert feeds.parse_date("2026-09-15T10:00:00.123+02:00", 0) == utc(2026, 9, 15, 8, 0)

# --- RSS 2.0 -------------------------------------------------------------

title, items = feeds.parse_feed(RSS.encode(), NOW)
assert title == "Example News", title
assert [item["title"] for item in items] == ["First & foremost", "Undated item", "Long one"], items
assert items[0]["link"] == "https://example.com/1"
assert items[0]["ts"] == utc(2026, 9, 15, 8, 30)
assert items[0]["summary"] == "Hello world & friends", items[0]["summary"]
assert items[1]["ts"] == NOW  # no date → fetch time
assert items[2]["ts"] == utc(2026, 9, 14, 18, 0)  # +0200 applied
assert len(items[2]["summary"]) == 160 and items[2]["summary"].endswith("…")

# --- Atom 1.0 ------------------------------------------------------------

title, entries = feeds.parse_feed(ATOM.encode(), NOW)
assert title == "Rust Blog", title
assert entries[0]["title"] == "Announcing Rust 1.99", entries[0]
assert entries[0]["link"] == "https://blog.example.org/1.99"  # alternate beats self
assert entries[0]["ts"] == utc(2026, 9, 15, 7, 15)  # published beats updated
assert entries[0]["summary"] == "Short summary"
assert entries[1]["link"] == "https://blog.example.org/audio.mp3"  # no alternate → the first link
assert entries[1]["ts"] == utc(2026, 9, 14, 10, 0)
assert entries[1]["summary"] == "Body text"  # content, tags stripped

# --- RSS 1.0 / RDF -------------------------------------------------------

title, wire = feeds.parse_feed(RDF.encode(), NOW)
assert title == "RDF Wire", title
assert len(wire) == 1 and wire[0]["title"] == "RDF headline" and wire[0]["link"] == "https://rdf.example.net/a"
assert wire[0]["ts"] == utc(2026, 9, 13, 6, 0) and wire[0]["summary"] == "Wire copy"

# --- not a feed ----------------------------------------------------------

for body in (b"<html><body>nope</body></html>", b"<rss><channel>", b""):
    try:
        feeds.parse_feed(body, NOW)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {body!r}")

# --- merge, buckets, URLs ------------------------------------------------

rust = {**feeds.new_entry("https://blog.example.org/feed.xml"), "title": "Rust Blog", "items": entries}
example = {**feeds.new_entry("https://example.com/feed"), "title": "Example News", "items": items}
merged = feeds.merged([rust, example])
assert [item["title"] for item in merged][:3] == ["Undated item", "First & foremost", "Announcing Rust 1.99"], merged
assert merged[0]["feed"] == "Example News" and merged[2]["feed"] == "Rust Blog"
assert len(feeds.merged([rust, example], 2)) == 2

assert feeds.day_bucket(NOW - 3 * 3600, NOW) == "today"
assert feeds.day_bucket(NOW + 3600, NOW) == "today"
assert feeds.day_bucket(NOW - 13 * 3600, NOW) == "yesterday"
assert feeds.day_bucket(NOW - 40 * 3600, NOW) == "earlier"  # the 13th, 20:00

assert feeds.normalize_url("  https://example.com/feed.xml ") == "https://example.com/feed.xml"
assert feeds.normalize_url("example.com/feed") == ""
assert feeds.normalize_url("ftp://example.com/feed") == ""
assert feeds.normalize_url(None) == ""
assert feeds.new_entry("https://hnrss.org/frontpage")["title"] == "hnrss.org"

# --- refresh rules: error keeps items, 304 keeps items, 200 replaces -------

entry = {**feeds.new_entry("https://example.com/feed"), "etag": '"v1"',
         "items": [{"title": "old", "link": "https://example.com/old", "ts": 1, "summary": ""}]}


def failing(url, etag, last_modified):
    raise urllib.error.URLError("name or service not known")


failed = feeds.refresh_feed(entry, 20, NOW, failing)
assert failed["items"] == entry["items"] and failed["error"] == "name or service not known", failed


def unchanged(url, etag, last_modified):
    assert etag == '"v1"', etag
    return 304, b"", etag, last_modified


same = feeds.refresh_feed({**entry, "error": "old error"}, 20, NOW, unchanged)
assert same["items"] == entry["items"] and same["error"] == ""


def fresh(url, etag, last_modified):
    return 200, RSS.encode(), '"v2"', "Tue, 15 Sep 2026 08:30:00 GMT"


new = feeds.refresh_feed(entry, 2, NOW, fresh)
assert new["title"] == "Example News" and new["etag"] == '"v2"' and len(new["items"]) == 2 and new["error"] == ""


def not_found(url, etag, last_modified):
    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


assert feeds.refresh_feed(entry, 20, NOW, not_found)["error"] == "HTTP 404"


def broken(url, etag, last_modified):
    return 200, b"<html><body>nope</body></html>", "", ""


assert "not an RSS or Atom feed" in feeds.refresh_feed(entry, 20, NOW, broken)["error"]

# --- cache round trip ----------------------------------------------------

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "feeds.json"
    feeds.save_cache(path, {"feeds": [new, {"url": "not a url"}, "junk"], "fetchedAt": NOW})
    cached = feeds.load_cache(path)
    assert cached["fetchedAt"] == NOW and len(cached["feeds"]) == 1
    assert cached["feeds"][0]["items"] == new["items"] and cached["feeds"][0]["etag"] == '"v2"'
    path.write_text("[]", encoding="utf-8")
    try:
        feeds.load_cache(path)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a cache that is not an object")

# --- markup --------------------------------------------------------------

EN = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
DE = json.loads((HERE / "locales" / "de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)
t = EN.__getitem__  # a missing key raises instead of leaking onto the screen

assert views.relative(NOW - 30, NOW, t) == "just now"
assert views.relative(NOW - 120, NOW, t) == "2 min ago"
assert views.relative(NOW - 7200, NOW, t) == "2 h ago"
assert views.relative(NOW - 86400, NOW, t) == "1 day ago"
assert views.relative(NOW - 3 * 86400, NOW, t) == "3 days ago"

tile = views.tile(merged[:5], True, 0, t)
assert 'data-rotator="up"' in tile and tile.count('<div class="sb-inline">') == 5, tile
assert "First &amp; foremost" in tile
assert "Add feeds" in views.tile([], False, 0, t)
assert "sb-warn" in views.tile([], True, 1, t) and "No headlines yet" in views.tile([], True, 1, t)
assert 'data-rotator' not in views.tile(merged[:1], True, 0, t)
# The RSS glyph opens the tile in every state, so the footprint never changes shape.
for state in (views.tile(merged[:5], True, 0, t), views.tile([], False, 0, t), views.tile([], True, 1, t)):
    assert state.index("<svg") < state.index("</span>") and 'width="16"' in state, state
assert views.hover(merged, True, t).count('class="sb-row"') == 3

snapshot = {"feeds": [example, rust], "updated_at": NOW, "busy": False, "draft": "", "form_error": ""}
fly = views.flyout(snapshot, merged, NOW, t)
assert 'data-tab="all"' in fly and fly.count("data-tab-panel=") == 3, fly
assert "Today" in fly and "Yesterday" in fly and "Earlier" not in fly
assert 'aria-label="Remove Example News"' in fly and 'data-value="https://example.com/feed"' in fly
assert 'href="https://blog.example.org/1.99"' in fly and 'data-action="add"' in fly
assert "Updated 12:00 · 2 feeds" in fly
empty = views.flyout({**snapshot, "feeds": []}, [], NOW, t)
assert "No feeds yet" in empty and "data-tabs" not in empty and 'data-action="add"' in empty
errored = views.flyout({**snapshot, "feeds": [failed], "busy": True, "form_error": t("news.duplicate")}, [], NOW, t)
assert "sb-alert--warn" in errored and "name or service not known" in errored
assert "Updating…" in errored and "already in the list" in errored
# A feed that never loaded is named by its host; that goes into <code>, a real title does not.
never = {**feeds.new_entry("https://feed.example.invalid/rss.xml"), "error": "timed out"}
assert "<code>feed.example.invalid</code>" in views.errors([never], t)
assert "<code>feed.example.invalid</code>" in views.feed_panel(never, NOW, t)
assert "<code>" not in views.feed_panel(rust, NOW, t)

print("ok")
