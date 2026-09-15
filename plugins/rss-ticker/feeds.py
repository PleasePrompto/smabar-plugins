"""Feed layer of the RSS Ticker: fetch, parse, merge and cache feeds.

Standard library only and no SDK import, so it runs and tests without the
bar. One walker serves three formats — RSS 2.0 (<rss><channel><item>),
Atom 1.0 (<feed><entry>) and RSS 1.0/RDF (<rdf:RDF><item>) — by matching
local tag names, so namespaces and prefixes never matter.
"""

import gzip
import html
import http.client
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

USER_AGENT = "smabar-rss-ticker/1.0"
TIMEOUT_SECONDS = 15
MAX_BYTES = 5 * 1024 * 1024
SUMMARY_CHARS = 160
FEED_ROOTS = ("rss", "feed", "RDF")
ITEM_TAGS = ("item", "entry")
# Document order matters less than this priority: an Atom entry lists
# <updated> before <published>, and the published date is the headline's.
DATE_TAGS = ("pubDate", "published", "updated", "date")
SUMMARY_TAGS = ("summary", "description", "content")
FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)
ITEM_KEYS = ("title", "link", "ts", "summary")

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")

Fetch = Callable[[str, str, str], tuple[int, bytes, str, str]]


# --- text and dates ------------------------------------------------------


def clean_text(raw: str | None, limit: int = 0) -> str:
    """Tags removed, entities decoded, whitespace collapsed, clipped to limit."""
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", raw or ""))).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def parse_date(raw: str | None, fallback: int) -> int:
    """RFC 822 (RSS) or ISO 8601 (Atom, Dublin Core) as epoch seconds.

    A missing or unreadable date becomes the fallback, normally the fetch time.
    """
    text = (raw or "").strip()
    if not text:
        return fallback
    for parser in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            parsed = parser(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp())
        except (ValueError, OverflowError, OSError):
            continue
    return fallback


# --- parsing -------------------------------------------------------------


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _text(element: ET.Element, *names: str) -> str:
    """Text of the first child matching the names, in the names' priority."""
    for name in names:
        for child in element:
            if _local(child.tag) == name and child.text and child.text.strip():
                return child.text
    return ""


def _link(element: ET.Element) -> str:
    """RSS <link>text</link>, or Atom's alternate <link href> — else the first."""
    first = ""
    for child in element:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or child.text or "").strip()
        if not href:
            continue
        if child.get("rel", "alternate") == "alternate":
            return href
        first = first or href
    return first


def parse_feed(body: bytes, fetched_at: int) -> tuple[str, list[dict]]:
    """(feed title, items in document order); raises ValueError for a non-feed.

    Items without a title or without an http(s) link are skipped; everything
    else keeps a bad date (fetch time) or a missing summary (empty string).
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError(f"not well-formed XML: {error}") from error
    if _local(root.tag) not in FEED_ROOTS:
        raise ValueError(f"not an RSS or Atom feed (root element <{_local(root.tag)}>)")
    channel = next((child for child in root if _local(child.tag) == "channel"), root)
    items = []
    for node in root.iter():
        if _local(node.tag) not in ITEM_TAGS:
            continue
        title = clean_text(_text(node, "title"))
        link = _link(node)
        if not title or not link.startswith(("http://", "https://")):
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "ts": parse_date(_text(node, *DATE_TAGS), fetched_at),
                "summary": clean_text(_text(node, *SUMMARY_TAGS), SUMMARY_CHARS),
            }
        )
    return clean_text(_text(channel, "title")), items


# --- fetching ------------------------------------------------------------


def normalize_url(raw: object) -> str:
    """The trimmed URL when it is an absolute http(s) address, else empty."""
    text = str(raw or "").strip()
    parts = urllib.parse.urlsplit(text)
    return text if parts.scheme in ("http", "https") and parts.netloc else ""


def new_entry(url: str) -> dict:
    """A feed that has never been fetched; the host stands in for its title."""
    return {
        "url": url,
        "title": urllib.parse.urlsplit(url).netloc or url,
        "etag": "",
        "lastModified": "",
        "error": "",
        "items": [],
    }


def fetch_feed(url: str, etag: str, last_modified: str) -> tuple[int, bytes, str, str]:
    """(status, body, etag, last_modified); status 304 means unchanged, no body."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip",
        },
    )
    if etag:
        request.add_header("If-None-Match", etag)
    if last_modified:
        request.add_header("If-Modified-Since", last_modified)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES + 1)
            headers = response.headers
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return 304, b"", etag, last_modified
        raise
    if headers.get("Content-Encoding", "").lower() == "gzip" and len(body) <= MAX_BYTES:
        body = gzip.decompress(body)
    if len(body) > MAX_BYTES:
        raise ValueError(f"feed is larger than {MAX_BYTES // 1024 // 1024} MB")
    return 200, body, headers.get("ETag", ""), headers.get("Last-Modified", "")


def describe(error: BaseException) -> str:
    """A short, user-readable reason for a failed fetch."""
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code}"
    if isinstance(error, urllib.error.URLError):
        return str(error.reason)
    if isinstance(error, TimeoutError):
        return "timed out"
    return str(error) or type(error).__name__


def refresh_feed(entry: dict, max_items: int, now: int, fetch: Fetch = fetch_feed) -> dict:
    """The feed refreshed: fresh items, unchanged (304), or the old items plus an error."""
    try:
        status, body, etag, last_modified = fetch(entry["url"], entry["etag"], entry["lastModified"])
        if status == 304:
            return {**entry, "error": "", "items": entry["items"][:max_items]}
        title, items = parse_feed(body, now)
    except FETCH_ERRORS as error:
        return {**entry, "error": describe(error)}
    # ponytail: feeds list newest first by convention, so the head is the newest slice.
    return {
        **entry,
        "title": title or entry["title"],
        "etag": etag,
        "lastModified": last_modified,
        "error": "",
        "items": items[:max_items],
    }


def refresh_all(entries: list[dict], max_items: int, now: int) -> list[dict]:
    """Every feed in its own thread; one slow feed costs at most one timeout."""
    results = list(entries)

    def work(index: int) -> None:
        results[index] = refresh_feed(entries[index], max_items, now)

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(len(entries))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


# --- reading -------------------------------------------------------------


def merged(feeds: list[dict], limit: int = 0) -> list[dict]:
    """Every item of every feed, newest first, each carrying its feed title."""
    items = [{**item, "feed": feed["title"]} for feed in feeds for item in feed["items"]]
    items.sort(key=lambda item: item["ts"], reverse=True)
    return items[:limit] if limit else items


def day_bucket(ts: int, now: int) -> str:
    """today, yesterday or earlier by the local calendar; future dates count as today."""
    days = (datetime.fromtimestamp(now).date() - datetime.fromtimestamp(ts).date()).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else "earlier"


# --- cache ---------------------------------------------------------------


def _cached_entry(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    url = normalize_url(raw.get("url"))
    if not url:
        return None
    entry = new_entry(url)
    for key in ("title", "etag", "lastModified", "error"):
        if isinstance(raw.get(key), str):
            entry[key] = raw[key]
    items = raw.get("items")
    entry["items"] = [
        {key: item[key] for key in ITEM_KEYS}
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
        and all(isinstance(item.get(key), str) for key in ("title", "link", "summary"))
        and isinstance(item.get("ts"), int)
    ]
    return entry


def load_cache(path: Path) -> dict:
    """{feeds, fetchedAt} from disk; raises OSError (FileNotFoundError included) or ValueError."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("feeds"), list):
        raise ValueError("cache is not a {feeds: [...]} object")
    fetched = raw.get("fetchedAt")
    return {
        "feeds": [entry for entry in map(_cached_entry, raw["feeds"]) if entry],
        "fetchedAt": fetched if isinstance(fetched, int) and not isinstance(fetched, bool) else 0,
    }


def save_cache(path: Path, data: dict) -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
