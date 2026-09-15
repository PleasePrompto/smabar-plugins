"""Markup of the RSS Ticker on the smabar UI kit: strings only, no SDK.

Every function returns HTML the plugin pushes with app.render. Feed titles,
headlines, summaries and links are external text and are escaped here.
"""

import json
import time
from collections.abc import Callable
from html import escape
from urllib.parse import urlsplit

from feeds import day_bucket, merged

Translator = Callable[[str], str]
TILE_CHARS = 34  # ponytail: a hard cut keeps the tile calm; a marquee in a tile overlaps whatever precedes it
FEED_CHARS = 14
HOVER_CHARS = 60
HOVER_ITEMS = 3
SUMMARY_CHARS = 52  # one line at the flyout's width
URL_CHARS = 44
MAX_TABS = 4  # ponytail: the 340px strip holds All plus four short labels; more feeds live in All
TAB_CHARS = {1: 22, 2: 16, 3: 11, 4: 7}  # label length by feed-tab count
ALL_ITEMS = 30  # ponytail: All shows the newest 30; each feed tab keeps its full maxPerFeed
ROTATE_MS = 6000
BUCKETS = (("today", "news.today"), ("yesterday", "news.yesterday"), ("earlier", "news.earlier"))


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "news.feeds", n=3)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def rss_icon(size: str) -> str:
    """The RSS glyph; the kit's icon set has none, so it is inline SVG."""
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>'
    )


GLYPH = f'<span class="sb-accent">{rss_icon("16")}</span>'  # opens every tile view; pixel sizes only survive the sanitizer


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def action(
    name: str,
    label: str,
    value: object = "",
    *,
    primary: bool = False,
    symbol: str = "",
    icon_only: bool = False,
) -> str:
    """A data-action button; icon-only buttons carry aria-label AND title."""
    encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    classes = "sb-btn sb-btn-primary" if primary else "sb-btn sb-btn-ghost"
    if icon_only:
        classes += " sb-btn-icon"
    accessible = (
        f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"' if icon_only else ""
    )
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    return (
        f'<button type="button" class="{classes}" data-action="{escape(name)}"'
        f' data-value="{escape(encoded, quote=True)}"{accessible}>{content}</button>'
    )


def feed_name(feed: dict, limit: int = 0) -> str:
    """The feed title, escaped; a bare host name (the title of a feed that never
    loaded) goes into <code>, which also keeps the shell's raw-locale-key check quiet."""
    title = clip(feed["title"], limit) if limit else feed["title"]
    return f"<code>{escape(title)}</code>" if feed["title"] == urlsplit(feed["url"]).netloc else escape(title)


def relative(ts: int, now: int, t: Translator) -> str:
    delta = max(0, now - ts)
    if delta < 60:
        return t("news.justNow")
    if delta < 3600:
        return tr(t, "news.minutesAgo", n=delta // 60)
    if delta < 86400:
        return tr(t, "news.hoursAgo", n=delta // 3600)
    days = delta // 86400
    return t("news.dayAgo") if days == 1 else tr(t, "news.daysAgo", n=days)


# --- tile and hover ------------------------------------------------------


def headline(item: dict) -> str:
    """One rotator view: the glyph, the feed name muted, then the clipped headline."""
    return (
        f'<div class="sb-inline">{GLYPH}<span class="sb-muted">{escape(clip(item["feed"], FEED_CHARS))}</span>'
        f'<span>{escape(clip(item["title"], TILE_CHARS))}</span></div>'
    )


def tile(items: list[dict], has_feeds: bool, failed: int, t: Translator) -> str:
    """Basic cover: the RSS glyph, then one headline at a time from the rotator."""
    if items:
        views = "".join(headline(item) for item in items)
        body = f'<div data-rotator="up" data-rotator-interval="{ROTATE_MS}">{views}</div>' if len(items) > 1 else views
    else:
        body = f'<div class="sb-inline">{GLYPH}<span class="sb-muted">{escape(t("news.addFeeds" if not has_feeds else "news.noItems"))}</span></div>'
    warn = '<span data-lucide="triangle-alert" class="sb-warn" aria-hidden="true"></span>' if failed else ""
    title = t("news.errorTitle") if failed else t("news.title")
    return f'<div class="sb-tile" title="{escape(title, quote=True)}">{body}{warn}</div>'


def hover(items: list[dict], has_feeds: bool, t: Translator) -> str:
    """The three newest headlines, one line each."""
    if not items:
        return f'<p class="sb-muted">{escape(t("news.addFeeds" if not has_feeds else "news.noItems"))}</p>'
    rows = "".join(
        f'<div class="sb-row"><span class="sb-faint">{escape(clip(item["feed"], FEED_CHARS))}</span>'
        f'<span>{escape(clip(item["title"], HOVER_CHARS))}</span></div>'
        for item in items[:HOVER_ITEMS]
    )
    return f'<div class="sb-section">{escape(t("news.title"))}</div><div class="sb-list">{rows}</div>'


# --- flyout --------------------------------------------------------------


def header(snapshot: dict, t: Translator) -> str:
    if snapshot["busy"]:
        meta = t("news.updating")
    elif snapshot["updated_at"]:
        meta = tr(t, "news.updated", time=time.strftime("%H:%M", time.localtime(snapshot["updated_at"])))
    else:
        meta = t("news.neverUpdated")
    count = len(snapshot["feeds"])
    if count:
        meta += " · " + (t("news.feedOne") if count == 1 else tr(t, "news.feeds", n=count))
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{rss_icon("20")}</span>'
        f'<div><h2 class="sb-title">{escape(t("news.title"))}</h2><p class="sb-meta">{escape(meta)}</p></div>'
        f'<div class="sb-header-actions">{action("refresh", t("news.refresh"), symbol="refresh-cw", icon_only=True)}</div></div>'
    )


def errors(feeds: list[dict], t: Translator) -> str:
    failed = [feed for feed in feeds if feed["error"]]
    if not failed:
        return ""
    lines = "<br>".join(f'{feed_name(feed)}: {escape(clip(feed["error"], 80))}' for feed in failed)
    return (
        f'<div class="sb-alert sb-alert--warn" role="alert"><span class="sb-alert__icon">{icon("triangle-alert")}</span>'
        f'<div><p class="sb-alert__title">{escape(t("news.errorTitle"))}</p><p class="sb-alert__text">{lines}</p></div></div>'
    )


def row(item: dict, now: int, show_feed: bool, t: Translator) -> str:
    when = escape(relative(item["ts"], now, t))
    meta = f'{escape(item["feed"])} · {when}' if show_feed else when
    summary = (
        f'<br><small class="sb-muted">{escape(clip(item["summary"], SUMMARY_CHARS))}</small>' if item["summary"] else ""
    )
    return (
        f'<div class="sb-row"><span class="sb-wrap"><a href="{escape(item["link"], quote=True)}">{escape(item["title"])}</a>'
        f'<br><small class="sb-faint">{meta}</small>{summary}</span></div>'
    )


def all_panel(items: list[dict], now: int, t: Translator) -> str:
    if not items:
        return f'<p class="sb-muted">{escape(t("news.noItems"))}</p>'
    groups: dict[str, list[dict]] = {key: [] for key, _label in BUCKETS}
    for item in items[:ALL_ITEMS]:
        groups[day_bucket(item["ts"], now)].append(item)
    return "".join(
        f'<div class="sb-section">{escape(t(label))}</div>'
        f'<div class="sb-list">{"".join(row(item, now, True, t) for item in groups[key])}</div>'
        for key, label in BUCKETS
        if groups[key]
    )


def feed_panel(feed: dict, now: int, t: Translator) -> str:
    remove = action("remove", tr(t, "news.remove", feed=feed["title"]), feed["url"], symbol="trash-2", icon_only=True)
    head = (
        f'<div class="sb-row"><span class="sb-wrap">{feed_name(feed)}<br>'
        f'<small class="sb-faint">{escape(clip(feed["url"], URL_CHARS))}</small></span>'
        f'<span class="sb-push">{remove}</span></div>'
    )
    items = merged([feed])
    if not items:
        return head + f'<p class="sb-muted">{escape(t("news.noItems"))}</p>'
    return head + f'<div class="sb-list">{"".join(row(item, now, False, t) for item in items)}</div>'


def tabs(feeds: list[dict], items: list[dict], now: int, t: Translator) -> str:
    """Shell-side tabs: All plus one per feed (the first MAX_TABS), no round-trip."""
    shown = feeds[:MAX_TABS]
    chars = TAB_CHARS[len(shown)]
    strip = f'<button type="button" class="sb-tab sb-active" data-tab="all">{escape(t("news.all"))}</button>' + "".join(
        f'<button type="button" class="sb-tab" data-tab="f{i}" title="{escape(feed["title"], quote=True)}">'
        f'{feed_name(feed, chars)}</button>'
        for i, feed in enumerate(shown)
    )
    panels = f'<div data-tab-panel="all">{all_panel(items, now, t)}</div>' + "".join(
        f'<div data-tab-panel="f{i}" hidden>{feed_panel(feed, now, t)}</div>' for i, feed in enumerate(shown)
    )
    return f'<div data-tabs><div class="sb-tabs">{strip}</div>{panels}</div>'


def empty(t: Translator) -> str:
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon" aria-hidden="true">{rss_icon("36")}</div>'
        f'<p class="sb-empty__title">{escape(t("news.emptyTitle"))}</p>'
        f'<p class="sb-empty__text">{escape(t("news.emptyText"))}</p></div>'
    )


def form(draft: str, error: str, t: Translator) -> str:
    problem = f'<p class="sb-error">{escape(error)}</p>' if error else ""
    return (
        '<form class="sb-stack"><div class="sb-field-stack">'
        f'<label class="sb-field__label" for="news-url">{escape(t("news.addLabel"))}</label>'
        '<div class="sb-field">'
        f'<input id="news-url" class="sb-input" type="url" data-field="url" value="{escape(draft, quote=True)}"'
        f' placeholder="{escape(t("news.addPlaceholder"), quote=True)}" required aria-describedby="news-url-hint news-url-error">'
        f'<button type="submit" class="sb-btn sb-btn-primary" data-action="add">{icon("plus")}{escape(t("news.add"))}</button></div>'
        f'<p class="sb-field__hint" id="news-url-hint">{escape(t("news.addHint"))}</p>'
        f'<p class="sb-field__error" id="news-url-error">{escape(t("news.invalidUrl"))}</p>{problem}</div></form>'
    )


def flyout(snapshot: dict, items: list[dict], now: int, t: Translator) -> str:
    feeds = snapshot["feeds"]
    body = tabs(feeds, items, now, t) if feeds else empty(t)
    return header(snapshot, t) + errors(feeds, t) + body + form(snapshot["draft"], snapshot["form_error"], t)
