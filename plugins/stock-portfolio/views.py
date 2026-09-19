"""Markup for the stock portfolio plugin.

Every function returns an HTML string that plugin.py pushes with app.render.
Nothing here imports the SDK, so the markup can be rendered and inspected
without a running bar. Only documented sb-* classes, data-* hooks and kit
tokens are used; inline styles carry only data values and the kit's heroTint
tokens. All external text -
symbols, instrument names, provider errors - goes through html.escape first.

Flyout structure, in the order a new user meets it:

  header          title, "add" and "refresh" actions
  tabs            Holdings | Watchlist | Add
  Holdings        hero + KPIs side by side, then the position table.
                  With nothing held it is an empty state WITH a button that
                  jumps straight to the Add tab.
  Watchlist       a table of quotes without a holding: symbol, intraday
                  trend, price over its day change, and a one-click route
                  into the portfolio.
  Add             a two-step flow: find the instrument, then say how much you
                  own - or follow it without owning it.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import portfolio

Translator = Callable[[str], str]

TILE = "portfolio"
LAYOUTS = ("statSplit", "dualText", "segmentHeader", "basic")
TABS = ("portfolio", "watchlist", "manage")

# Shown as one-tap chips in the Add tab so the first symbol is never a guess.
# These are Yahoo symbols, so the chips are hidden for other providers.
QUICK_PICKS = (
    ("^GDAXI", "DAX"),
    ("^GSPC", "S&P 500"),
    ("^NDX", "Nasdaq 100"),
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
)


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "sp.heroCaption", count=3, currency="EUR")."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def _q(text: object) -> str:
    """Escape for an attribute value."""
    return escape(str(text), quote=True)


def _tween(lang: str, key: str) -> str:
    """Count-up animation for a changed number.

    The shell animates the FIRST plain number in the element's text. German
    number style writes the decimal separator as a comma, which that parser
    would read as the end of the number, so the hook is only attached for
    number styles where it behaves correctly. Purely cosmetic either way.
    """
    if str(lang or "en").lower().startswith("de"):
        return ""
    return f' data-sb-tween data-sb-key="{_q(key)}"'


def _delta_class(value: float | None) -> str:
    if not portfolio.is_number(value):
        return "sb-stat__delta"
    return "sb-stat__delta sb-stat__delta--" + ("up" if value >= 0 else "down")


def _delta(value: float | None, lang: str, title: str = "") -> str:
    """A signed, coloured percentage that still reads without colour."""
    if not portfolio.is_number(value):
        return f'<span class="sb-faint">{portfolio.NO_DATA}</span>'
    attr = f' title="{_q(title)}"' if title else ""
    return (
        f'<span class="{_delta_class(value)}"{attr}>'
        f"{escape(portfolio.fmt_percent(value, lang))}</span>"
    )


def change_badge(pct: float | None, lang: str) -> str:
    """Never colour alone: the badge carries a trend icon and a signed value."""
    if not portfolio.is_number(pct):
        return f'<span class="sb-badge">{portfolio.NO_DATA}</span>'
    up = pct >= 0
    variant = "sb-badge-success" if up else "sb-badge-danger"
    glyph = "trending-up" if up else "trending-down"
    return (
        f'<span class="sb-badge {variant}">{icon(glyph)}'
        f"{escape(portfolio.fmt_percent(pct, lang))}</span>"
    )


def _avatar(symbol: str) -> str:
    """Initials in a circle: the recognisable mark a logo would be."""
    return (
        '<span class="sb-avatar sb-avatar--sm" aria-hidden="true">'
        f"{escape(portfolio.initials(symbol))}</span>"
    )


def _name(text: str, limit: int = 20) -> str:
    """Provider names can be long; a row has room for a short one.

    The full name stays available as the tooltip. The cap keeps the table's
    natural width inside the flyout, so numbers never wrap.
    """
    text = str(text or "")
    if len(text) <= limit:
        return f'<small class="sb-faint">{escape(text)}</small>'
    short = text[: limit - 1].rstrip() + "\u2026"
    return f'<small class="sb-faint" title="{_q(text)}">{escape(short)}</small>'


def _spark(points: str, label: str, extra: str = "sb-accent") -> str:
    if not points:
        return ""
    classes = f"sb-spark {extra}".strip()
    return (
        f'<span class="{classes}" data-chart="sparkline" data-points="{_q(points)}"'
        f' role="img" aria-label="{_q(label)}"></span>'
    )


def _sortable(label: str, numeric: bool = False) -> str:
    """A table header the shell can sort by (data-sb-sort)."""
    kind = '="number"' if numeric else ""
    classes = ' class="sb-table__num"' if numeric else ""
    return (
        f'<th scope="col"{classes} data-sb-sort{kind}>'
        f'<button type="button" class="sb-table__sort">{escape(label)}</button></th>'
    )


def _sr_header(label: str) -> str:
    """A column whose header is only read out, not shown (trend, actions)."""
    return f'<th scope="col"><span class="sb-sr-only">{escape(label)}</span></th>'


def _button(
    action: str,
    label: str,
    value: str = "",
    *,
    symbol: str = "",
    variant: str = "sb-btn-ghost",
    icon_only: bool = False,
    submit: bool = False,
) -> str:
    classes = f"sb-btn {variant}".strip()
    if icon_only:
        classes += " sb-btn-icon"
    named = (
        f' aria-label="{_q(label)}" title="{_q(label)}"'
        if icon_only
        else f' title="{_q(label)}"'
    )
    value_attr = f' data-value="{_q(value)}"' if value else ""
    body = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    kind = "submit" if submit else "button"
    return (
        f'<button type="{kind}" class="{classes}" data-action="{_q(action)}"'
        f"{value_attr}{named}>{body}</button>"
    )


# ------------------------------------------------------------------- tile


def _cover(
    layout: str,
    label: str,
    value: str,
    pct: float | None,
    points: str,
    sub: str,
    key: str,
    lang: str,
    glyph: str,
) -> str:
    """One bar-tile view in the chosen cover recipe (ui_kit coverLayouts).

    `sub` is the absolute move; it fills the trend slot while there are too
    few points for a sparkline, so the label is never printed twice.
    """
    delta_text = escape(portfolio.fmt_percent(pct, lang))
    delta = (
        f'<span class="{_delta_class(pct)}"{_tween(lang, key)}>{delta_text}</span>'
        if portfolio.is_number(pct)
        else f'<span class="sb-muted">{portfolio.NO_DATA}</span>'
    )
    value_html = f'<span class="sb-mono">{escape(value)}</span>'
    if layout == "basic":
        return f'<span class="sb-inline">{icon(glyph)}{value_html}</span>'
    if layout == "dualText":
        return (
            '<span class="sb-inline"><span class="sb-tile-stack">'
            f"{value_html}{delta}</span></span>"
        )
    if layout == "segmentHeader":
        return (
            '<span class="sb-inline"><span class="sb-tile-seg">'
            f'<span>{escape(label)}</span><span class="sb-mono">{escape(value)}</span>'
            "</span></span>"
        )
    trend = _spark(points, label) or f'<span class="sb-muted">{escape(sub)}</span>'
    return (
        '<span class="sb-inline"><span class="sb-tile-split">'
        f'<span class="sb-tile-stack">{value_html}'
        f'<span class="sb-muted" data-marquee style="max-width: 6rem">'
        f"{escape(label)}</span></span>"
        f'<span class="sb-tile-stack">{delta}{trend}</span>'
        "</span></span>"
    )


def tile(data: dict, cfg: dict, t: Translator, lang: str) -> str:
    """The bar tile: portfolio total first, optionally rolling through symbols.

    Every state - loading, error, empty and ready - keeps the same structure
    and a placeholder where the value belongs, so the tile never changes shape.
    """
    layout = cfg["coverLayout"] if cfg["coverLayout"] in LAYOUTS else LAYOUTS[0]
    base = cfg["baseCurrency"]
    quotes = data["quotes"]
    rows = [
        portfolio.position_row(position, quotes, base, data["fx"])
        for position in cfg["positions"]
    ]
    sums = portfolio.totals(rows)
    warn = (
        f'<span class="sb-warn">{icon("triangle-alert")}</span>' if data["error"] else ""
    )

    views: list[str] = []
    if cfg["positions"]:
        total_text = (
            portfolio.fmt_money_compact(sums["value"], base, lang)
            if sums["value"] is not None
            else portfolio.NO_DATA
        )
        views.append(
            _cover(
                layout,
                t("sp.portfolio"),
                total_text,
                sums["dayPct"],
                portfolio.spark_points(data["history"]),
                portfolio.fmt_signed_money(sums["dayAbs"], base, lang, compact=True),
                "total",
                lang,
                "wallet",
            )
        )
    for symbol in cfg["symbols"] if cfg["tileRotate"] else []:
        quote = quotes.get(symbol)
        if not quote:
            continue
        move, pct = portfolio.quote_change(quote)
        points = quote.get("points") or data["series"].get(symbol) or []
        views.append(
            _cover(
                layout,
                symbol,
                portfolio.fmt_price(quote.get("price"), quote.get("currency"), lang),
                pct,
                portfolio.spark_points(points),
                portfolio.fmt_signed_money(move, quote.get("currency"), lang),
                f"sym-{symbol}",
                lang,
                "chart-line",
            )
        )
    if not views:
        views.append(
            _cover(
                layout,
                t("sp.portfolio"),
                portfolio.NO_DATA,
                None,
                "",
                portfolio.NO_DATA,
                "total",
                lang,
                "wallet",
            )
        )

    if cfg["positions"]:
        title = tr(
            t,
            "sp.tileTitle",
            value=portfolio.fmt_money(sums["value"], base, lang)
            if sums["value"] is not None
            else portfolio.NO_DATA,
            change=portfolio.fmt_percent(sums["dayPct"], lang),
            count=len(cfg["positions"]),
        )
    else:
        title = t("sp.tileEmptyTitle")
    if len(views) > 1:
        # The rotator stacks its views in one cell, so the tile keeps the width
        # of the widest view instead of resizing while it rolls.
        inner = (
            '<span data-rotator="up" data-rotator-interval="5000">'
            + "".join(views)
            + "</span>"
        )
    else:
        inner = views[0]
    return f'<div class="sb-tile" title="{_q(title)}">{inner}{warn}</div>'


# ------------------------------------------------------------------ hover


def _hover_row(label: str, value: str, pct: float | None, lang: str) -> str:
    return (
        f'<div class="sb-row"><b>{escape(label)}</b>'
        f'<span class="sb-push"><span class="sb-mono">{escape(value)}</span> '
        f"{change_badge(pct, lang)}</span></div>"
    )


def hover(data: dict, cfg: dict, t: Translator, lang: str) -> str:
    """Compact read-only preview: the totals and every tracked symbol."""
    base = cfg["baseCurrency"]
    rows = [
        portfolio.position_row(position, data["quotes"], base, data["fx"])
        for position in cfg["positions"]
    ]
    sums = portfolio.totals(rows)
    body = f'<div class="sb-section">{escape(t("sp.title"))}</div>'
    lines = []
    if cfg["positions"]:
        lines.append(
            _hover_row(
                t("sp.portfolio"),
                portfolio.fmt_money(sums["value"], base, lang)
                if sums["value"] is not None
                else portfolio.NO_DATA,
                sums["dayPct"],
                lang,
            )
        )
    for symbol in cfg["symbols"]:
        quote = data["quotes"].get(symbol)
        if not quote:
            continue
        _, pct = portfolio.quote_change(quote)
        lines.append(
            _hover_row(
                symbol,
                portfolio.fmt_price(quote.get("price"), quote.get("currency"), lang),
                pct,
                lang,
            )
        )
    if lines:
        body += f'<div class="sb-list">{"".join(lines)}</div>'
    else:
        body += (
            f'<div class="sb-card"><p class="sb-dim">{escape(t("sp.emptyHint"))}</p></div>'
        )
    body += f'<p class="sb-meta">{escape(t("sp.hoverHint"))}</p>'
    return body


# ----------------------------------------------------------------- flyout


def _header(t: Translator, busy: bool) -> str:
    spinner = (
        f'<span class="sb-spinner" role="status" aria-label="{_q(t("sp.loading"))}">'
        "</span>"
        if busy
        else ""
    )
    return (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("chart-line")}</span>'
        f'<span class="sb-title">{escape(t("sp.title"))}</span>'
        f'<div class="sb-header-actions">{spinner}'
        + _button(
            "select-tab",
            t("sp.addTitle"),
            "manage",
            symbol="plus",
            icon_only=True,
        )
        + _button("refresh", t("sp.refresh"), symbol="refresh-cw", icon_only=True)
        + "</div></div>"
    )


def _alert(kind: str, title: str, text: str, glyph: str) -> str:
    return (
        f'<div class="sb-alert sb-alert--{kind}" role="alert">'
        f'<span class="sb-alert__icon">{icon(glyph)}</span>'
        f'<div><div class="sb-alert__title">{escape(title)}</div>'
        f'<div class="sb-alert__text">{escape(text)}</div></div></div>'
    )


def _tabs_strip(active: str, t: Translator, counts: dict) -> str:
    """The tab strip. Counts make it obvious where the content lives."""
    labels = {
        "portfolio": t("sp.tabHoldings"),
        "watchlist": t("sp.watchlist"),
        "manage": t("sp.tabAdd"),
    }
    buttons = []
    for tab in TABS:
        classes = "sb-tab sb-active" if tab == active else "sb-tab"
        count = counts.get(tab)
        suffix = f" ({count})" if count else ""
        buttons.append(
            f'<button type="button" class="{classes}" data-tab="{tab}"'
            f' data-action="select-tab" data-value="{tab}">'
            f"{escape(labels[tab])}{escape(suffix)}</button>"
        )
    return f'<div class="sb-tabs">{"".join(buttons)}</div>'


def _empty(title: str, text: str, glyph: str, action: str = "") -> str:
    """An empty state that says what to do AND offers the control to do it."""
    return (
        f'<div class="sb-empty"><div class="sb-empty__icon">{icon(glyph)}</div>'
        f'<p class="sb-empty__title">{escape(title)}</p>'
        f'<div class="sb-stack sb-center"><p class="sb-empty__text">{escape(text)}</p>'
        f"{action}</div></div>"
    )


def _hero(sums: dict, data: dict, cfg: dict, t: Translator, lang: str) -> str:
    base = cfg["baseCurrency"]
    value = (
        portfolio.fmt_money(sums["value"], base, lang)
        if sums["value"] is not None
        else portfolio.NO_DATA
    )
    caption = tr(t, "sp.heroCaption", count=sums["valued"], currency=base)
    move = ""
    if sums["dayAbs"] is not None:
        move = (
            ' <span class="sb-dim">'
            f"{escape(portfolio.fmt_signed_money(sums['dayAbs'], base, lang))}</span>"
        )
    points = portfolio.spark_points(data["history"])
    spark = _spark(points, tr(t, "sp.sparkLabel", count=len(data["history"])), "")
    return (
        f'<div class="sb-hero"{_hero_tint(sums["dayPct"])}>'
        f"<small>{escape(caption)}</small><h1>{escape(value)}</h1>"
        f'<div class="sb-inline">{change_badge(sums["dayPct"], lang)}{move}</div>'
        f"{spark}</div>"
    )


def _hero_tint(pct: float | None) -> str:
    """The kit's heroTint recipe, fed with the theme's own status colour.

    A gaining day paints the hero green, a losing one red. The colour is
    darkened so white text stays legible on every theme, and the badge next
    to the value carries the same information without colour.
    """
    if not portfolio.is_number(pct):
        return ""
    tone = "success" if pct >= 0 else "danger"
    return (
        ' style="--sb-accent-gradient: linear-gradient(135deg,'
        f" color-mix(in srgb, var(--sb-{tone}) 80%, #000),"
        f" color-mix(in srgb, var(--sb-{tone}) 45%, #000));"
        ' --sb-on-accent: #fff"'
    )


def _kpi(value: str, label: str, title: str, tone: str = "") -> str:
    """One cell: a compact figure, its caption, the exact reading as tooltip."""
    classes = f"sb-kpi-value {tone}".strip()
    return (
        f'<div class="sb-kpi" title="{_q(title)}">'
        f'<span class="{classes}">{escape(value)}</span>'
        f'<span class="sb-kpi-label">{escape(label)}</span></div>'
    )


def _kpis(rows: list[dict], sums: dict, cfg: dict, t: Translator, lang: str) -> str:
    """Four cells: the day, the total gain, what was invested, today's outlier."""
    base = cfg["baseCurrency"]

    def money(value: float | None, compact: bool = False) -> str:
        return portfolio.fmt_signed_money(value, base, lang, compact=compact)

    def with_pct(label: str, pct: float | None) -> str:
        if pct is None:
            return label
        return f"{label} {portfolio.fmt_percent(pct, lang)}"

    cells = _kpi(
        money(sums["dayAbs"], compact=True),
        with_pct(t("sp.dayChange"), sums["dayPct"]),
        f'{t("sp.dayChange")}: {money(sums["dayAbs"])}',
        _delta_class(sums["dayAbs"]),
    )
    cells += _kpi(
        money(sums["gainAbs"], compact=True),
        with_pct(t("sp.totalGain"), sums["gainPct"]),
        f'{t("sp.totalGain")}: {money(sums["gainAbs"])}',
        _delta_class(sums["gainAbs"]),
    )
    cost = sums["cost"]
    cells += _kpi(
        portfolio.fmt_money_compact(cost, base, lang) if cost is not None else portfolio.NO_DATA,
        t("sp.invested"),
        f'{t("sp.invested")}: '
        + (portfolio.fmt_money(cost, base, lang) if cost is not None else portfolio.NO_DATA),
    )
    mover = portfolio.top_mover(rows)
    if mover:
        cells += _kpi(
            portfolio.fmt_percent(mover["dayPct"], lang),
            f'{t("sp.topMover")} \u00b7 {mover["symbol"]}',
            f'{mover["symbol"]}: {portfolio.fmt_percent(mover["dayPct"], lang)}',
            _delta_class(mover["dayPct"]),
        )
    else:
        cells += _kpi(portfolio.NO_DATA, t("sp.topMover"), t("sp.topMover"))
    return f'<div class="sb-kpi-grid">{cells}</div>'


def _position_table(rows: list[dict], cfg: dict, t: Translator, lang: str) -> str:
    """Six calm columns: what it is, how much, what it is worth, how it moved.

    Shares and price share one cell ("10 x 150.00 EUR") so the table reads at
    the flyout's width instead of turning into a spreadsheet.
    """
    base = cfg["baseCurrency"]
    head = (
        "<thead><tr>"
        + _sortable(t("sp.colPosition"))
        + f'<th scope="col" class="sb-table__num">{escape(t("sp.colHolding"))}</th>'
        + _sortable(t("sp.colValue"), numeric=True)
        + _sortable(t("sp.colDay"), numeric=True)
        + _sortable(t("sp.colGain"), numeric=True)
        + _sr_header(t("sp.colActions"))
        + "</tr></thead>"
    )

    body = []
    for row in rows:
        holding = (
            f"{portfolio.fmt_shares(row['shares'], lang)} \u00d7 "
            f"{portfolio.fmt_price(row['price'], row['currency'], lang)}"
            if row["hasQuote"]
            else f"{portfolio.fmt_shares(row['shares'], lang)} \u00d7 {portfolio.NO_DATA}"
        )
        if not row["hasQuote"]:
            value_cell = (
                f'<span class="sb-badge sb-badge-warning">{escape(t("sp.noQuote"))}</span>'
            )
        elif row["value"] is None:
            value_cell = (
                '<span class="sb-badge sb-badge-warning" '
                f'title="{_q(tr(t, "sp.noRate", currency=row["currency"], base=base))}">'
                f"{escape(row['currency'])}</span>"
            )
        else:
            value_cell = escape(portfolio.fmt_money(row["value"], base, lang))
        gain_cell = (
            _delta(
                row["gainPct"],
                lang,
                portfolio.fmt_money(row["gainAbs"], base, lang)
                if row["gainAbs"] is not None
                else "",
            )
            if row["gainPct"] is not None
            else f'<span class="sb-faint" title="{_q(t("sp.noBuyPrice"))}">'
            f"{portfolio.NO_DATA}</span>"
        )
        menu = (
            '[{"action":"edit-position","value":%s,"label":%s,"icon":"pencil"},'
            '{"action":"remove-position","value":%s,"label":%s,"icon":"trash-2",'
            '"danger":true}]'
        ) % (
            _json_string(row["symbol"]),
            _json_string(tr(t, "sp.editPosition", symbol=row["symbol"])),
            _json_string(row["symbol"]),
            _json_string(tr(t, "sp.removePosition", symbol=row["symbol"])),
        )
        body.append(
            f"<tr data-context-items='{escape(menu, quote=True)}'>"
            f'<td><span class="sb-table__person">{_avatar(row["symbol"])}'
            f'<span><b>{escape(row["symbol"])}</b><br>{_name(row["name"])}</span></span></td>'
            f'<td class="sb-table__num">{escape(holding)}</td>'
            f'<td class="sb-table__num">{value_cell}</td>'
            f'<td class="sb-table__num">{_delta(row["dayPct"], lang)}</td>'
            f'<td class="sb-table__num">{gain_cell}</td>'
            "<td>"
            + _button(
                "edit-position",
                tr(t, "sp.editPosition", symbol=row["symbol"]),
                row["symbol"],
                symbol="pencil",
                icon_only=True,
            )
            + _button(
                "remove-position",
                tr(t, "sp.removePosition", symbol=row["symbol"]),
                row["symbol"],
                symbol="trash-2",
                icon_only=True,
            )
            + "</td></tr>"
        )
    return (
        '<div class="sb-table-wrap" role="region" tabindex="0"'
        ' aria-labelledby="sp-positions-caption">'
        '<table class="sb-table sb-table--hover" id="sp-positions">'
        '<caption class="sb-sr-only" id="sp-positions-caption">'
        f'{escape(t("sp.tableCaption"))}</caption>'
        f'{head}<tbody>{"".join(body)}</tbody></table></div>'
    )


def _json_string(text: str) -> str:
    """A JSON string literal for the data-context-items attribute."""
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("\n", " ")[:64] + '"'


def _portfolio_panel(
    rows: list[dict], sums: dict, data: dict, cfg: dict, t: Translator, lang: str
) -> str:
    if not cfg["positions"]:
        return _empty(
            t("sp.emptyTitle"),
            t("sp.emptyHint"),
            "wallet",
            _button(
                "select-tab",
                t("sp.addFirst"),
                "manage",
                symbol="plus",
                variant="sb-btn-primary",
            ),
        )
    # At the flyout's wide width the summary sits beside the KPIs; below
    # 36rem of available width sb-split stacks them on its own.
    panel = (
        '<div class="sb-split">'
        f"<section>{_hero(sums, data, cfg, t, lang)}</section>"
        f"<section>{_kpis(rows, sums, cfg, t, lang)}</section>"
        "</div>"
    )
    panel += _position_table(rows, cfg, t, lang)
    if sums["unconverted"]:
        panel += (
            f'<p class="sb-meta">'
            + escape(
                tr(
                    t,
                    "sp.unconvertedNote",
                    symbols=", ".join(sums["unconverted"]),
                    base=cfg["baseCurrency"],
                )
            )
            + "</p>"
        )
    return panel


def _watch_row(
    symbol: str, quote: dict | None, data: dict, t: Translator, lang: str
) -> str:
    """One watched quote: symbol, trend, price over its day change, actions."""
    controls = _button(
        "pick",
        tr(t, "sp.buyThis", symbol=symbol),
        symbol,
        symbol="plus",
        icon_only=True,
    ) + _button(
        "remove-watch",
        tr(t, "sp.removeWatch", symbol=symbol),
        symbol,
        symbol="x",
        icon_only=True,
    )
    who = (
        f'<td><span class="sb-table__person">{_avatar(symbol)}'
        f'<span><b>{escape(symbol)}</b><br>{_name((quote or {}).get("name") or symbol)}'
        "</span></span></td>"
    )
    if not quote:
        return (
            f"<tr>{who}<td></td>"
            f'<td class="sb-table__num"><span class="sb-badge sb-badge-warning">'
            f'{escape(t("sp.noQuote"))}</span></td><td>{controls}</td></tr>'
        )
    _, pct = portfolio.quote_change(quote)
    points = quote.get("points") or data["series"].get(symbol) or []
    spark = _spark(
        portfolio.spark_points(points), tr(t, "sp.symbolSpark", symbol=symbol)
    )
    price = portfolio.fmt_price(quote.get("price"), quote.get("currency"), lang)
    return (
        f"<tr>{who}<td>{spark}</td>"
        f'<td class="sb-table__num"><span class="sb-mono">{escape(price)}</span><br>'
        f"{change_badge(pct, lang)}</td><td>{controls}</td></tr>"
    )


def _watchlist_panel(data: dict, cfg: dict, t: Translator, lang: str) -> str:
    if not cfg["watchlist"]:
        return _empty(
            t("sp.watchEmptyTitle"),
            t("sp.watchEmptyHint"),
            "eye",
            _button(
                "select-tab",
                t("sp.watchSearch"),
                "manage",
                symbol="search",
                variant="sb-btn-primary",
            ),
        )
    rows = "".join(
        _watch_row(symbol, data["quotes"].get(symbol), data, t, lang)
        for symbol in cfg["watchlist"]
    )
    head = (
        "<thead><tr>"
        + _sortable(t("sp.fieldSymbol"))
        + _sr_header(t("sp.colTrend"))
        + _sortable(t("sp.colPrice"), numeric=True)
        + _sr_header(t("sp.colActions"))
        + "</tr></thead>"
    )
    return (
        '<div class="sb-table-wrap" role="region" tabindex="0"'
        ' aria-labelledby="sp-watch-caption">'
        '<table class="sb-table sb-table--hover" id="sp-watch">'
        '<caption class="sb-sr-only" id="sp-watch-caption">'
        f'{escape(t("sp.watchCaption"))}</caption>'
        f'{head}<tbody>{rows}</tbody></table></div>'
        f'<p class="sb-meta">{escape(t("sp.watchHint"))}</p>'
    )


def _stepper(picked: bool, t: Translator) -> str:
    """Two steps, so the flow reads before anything is typed."""
    first = "sb-stepper__step is-done" if picked else "sb-stepper__step is-current"
    second = "sb-stepper__step is-current" if picked else "sb-stepper__step"
    current = ' aria-current="step"'
    return (
        f'<ol class="sb-stepper" role="list" aria-label="{_q(t("sp.stepperLabel"))}">'
        f'<li class="{first}"{"" if picked else current}>'
        '<span class="sb-stepper__marker" aria-hidden="true"></span>'
        f'<span class="sb-stepper__label">{escape(t("sp.step1"))}</span></li>'
        f'<li class="{second}"{current if picked else ""}>'
        '<span class="sb-stepper__marker" aria-hidden="true"></span>'
        f'<span class="sb-stepper__label">{escape(t("sp.step2"))}</span></li></ol>'
    )


def _quick_picks(cfg: dict, t: Translator) -> str:
    """One tap to a known-good symbol; Yahoo symbols, so Yahoo only."""
    if cfg["provider"] != "yahoo":
        return ""
    chips = "".join(
        f'<button type="button" class="sb-chip" data-action="pick"'
        f' data-value="{_q(symbol)}" title="{_q(symbol)}">{escape(label)}</button>'
        for symbol, label in QUICK_PICKS
    )
    return (
        f'<div class="sb-cluster"><span class="sb-muted">{escape(t("sp.quickPicks"))}</span>'
        f"{chips}</div>"
    )


def _search_results(data: dict, cfg: dict, t: Translator) -> str:
    if data["searching"]:
        # Skeleton lines while the provider answers; "nothing found" waits.
        status = tr(t, "sp.searching", query=data["query"])
        return (
            '<div class="sb-reveal sb-active" aria-busy="true">'
            f'<p class="sb-dim" role="status">{escape(status)}</p>'
            f'<p class="sb-skeleton">{escape(status)}</p>'
            f'<p class="sb-skeleton">{escape(status)}</p></div>'
        )
    rows = []
    for result in data["results"]:
        symbol = result["symbol"]
        meta = " \u00b7 ".join(
            part for part in (result.get("kind"), result.get("exchange")) if part
        )
        if symbol in cfg["symbols"]:
            control = (
                f'<span class="sb-badge sb-badge-success">{escape(t("sp.tracked"))}</span>'
            )
        else:
            control = _button(
                "pick",
                tr(t, "sp.pick", symbol=symbol),
                symbol,
                symbol="check",
                variant="sb-btn",
            )
        rows.append(
            f'<div class="sb-row"><span><b>{escape(symbol)}</b><br>'
            f'<small class="sb-faint">{escape(result["name"])}'
            f'{(" \u00b7 " + escape(meta)) if meta else ""}</small></span>'
            f'<span class="sb-push"></span>{control}</div>'
        )
    active = " sb-active" if rows else ""
    return (
        f'<div class="sb-reveal{active}"><div class="sb-list">{"".join(rows)}</div></div>'
    )


def _manage_panel(data: dict, cfg: dict, t: Translator, lang: str) -> str:
    """Step 1 finds the instrument, step 2 says what to do with it."""
    draft = data["draft"]
    picked = bool(draft.get("symbol"))
    editing = bool(draft.get("editing"))

    panel = _stepper(picked, t)
    panel += (
        '<form class="sb-stack"><div class="sb-field-stack">'
        f'<label class="sb-field__label" for="sp-query">{escape(t("sp.searchLabel"))}</label>'
        '<div class="sb-field">'
        f'<input class="sb-input" id="sp-query" data-field="query" type="search"'
        f' maxlength="64" value="{_q(data["query"])}"'
        f' placeholder="{_q(t("sp.searchPlaceholder"))}" aria-describedby="sp-query-hint">'
        + _button(
            "search",
            t("sp.search"),
            symbol="search",
            variant="sb-btn-primary",
            submit=True,
        )
        + "</div>"
        f'<p class="sb-field__hint" id="sp-query-hint">{escape(t("sp.searchHint"))}</p>'
        "</div></form>"
    )
    panel += _quick_picks(cfg, t)
    panel += _search_results(data, cfg, t)
    if data["formError"]:
        panel += f'<p class="sb-error">{escape(data["formError"][:160])}</p>'
    elif data["query"] and not data["results"] and not data["searching"]:
        panel += _empty(t("sp.noResultsTitle"), t("sp.noResults"), "search")

    if editing:
        subtitle = t("sp.editTitle")
    else:
        subtitle = draft.get("name") or t("sp.newEntryHint")
    chosen = (
        f'<span class="sb-icon-badge">{icon("chart-line")}</span>'
        f'<span><b>{escape(draft.get("symbol") or t("sp.newEntry"))}</b><br>'
        f'<small class="sb-faint">{escape(subtitle)}</small></span>'
    )
    card = (
        '<div class="sb-card sb-card--accent"><div class="sb-card__body">'
        f'<div class="sb-inline">{chosen}<span class="sb-push"></span>'
        + (
            _button("cancel-edit", t("sp.clear"), symbol="x", icon_only=True)
            if picked
            else ""
        )
        + "</div>"
        '<form class="sb-stack">'
        '<div class="sb-field-stack">'
        f'<label class="sb-field__label" for="sp-symbol">{escape(t("sp.fieldSymbol"))}</label>'
        f'<input class="sb-input" id="sp-symbol" data-field="posSymbol" type="text"'
        f' required maxlength="24" value="{_q(draft.get("symbol", ""))}"'
        f' placeholder="{_q(t("sp.symbolPlaceholder"))}" aria-describedby="sp-symbol-hint">'
        f'<p class="sb-field__hint" id="sp-symbol-hint">{escape(t("sp.symbolHint"))}</p>'
        "</div>"
        '<div class="sb-field-stack">'
        f'<label class="sb-field__label" for="sp-shares">{escape(t("sp.fieldShares"))}</label>'
        f'<input class="sb-input" id="sp-shares" data-field="posShares" type="number"'
        f' required min="0.0001" step="any" value="{_q(draft.get("shares", ""))}"'
        f' placeholder="{_q(t("sp.sharesPlaceholder"))}" aria-describedby="sp-shares-hint">'
        f'<p class="sb-field__hint" id="sp-shares-hint">{escape(t("sp.sharesHint"))}</p>'
        "</div>"
        '<div class="sb-field-stack">'
        f'<label class="sb-field__label" for="sp-buy">{escape(t("sp.fieldBuy"))}'
        f' <span class="sb-meta">\u00b7 {escape(t("sp.optional"))}</span></label>'
        f'<input class="sb-input" id="sp-buy" data-field="posBuy" type="number"'
        f' min="0" step="any" value="{_q(draft.get("buyPrice", ""))}"'
        f' placeholder="{_q(t("sp.buyPlaceholder"))}" aria-describedby="sp-buy-hint">'
        f'<p class="sb-field__hint" id="sp-buy-hint">{escape(t("sp.buyHint"))}</p>'
        "</div>"
        '<div class="sb-cluster">'
        + _button(
            "add-position",
            t("sp.saveEdit") if editing else t("sp.addToDepot"),
            symbol="wallet",
            variant="sb-btn-primary",
            submit=True,
        )
        + (
            ""
            if editing
            else _button("add-watch", t("sp.watchOnly"), symbol="eye", variant="sb-btn")
        )
        + "</div></form>"
    )
    if data["positionError"]:
        card += _alert(
            "danger", t("sp.saveFailed"), data["positionError"][:160], "circle-alert"
        )
    elif data["positionOk"]:
        card += _alert("ok", t("sp.saved"), data["positionOk"][:160], "circle-check")
    card += "</div></div>"

    panel += card
    panel += (
        f'<div class="sb-tip">{icon("info")}<span>{escape(t("sp.addTip"))}</span></div>'
    )
    panel += (
        '<details class="sb-collapsible"><summary>'
        f'{escape(t("sp.settingsTitle"))}</summary>'
        '<div class="sb-collapsible__body"><p class="sb-dim">'
        + escape(
            tr(
                t,
                "sp.settingsHint",
                base=cfg["baseCurrency"],
                provider=cfg["provider"],
                minutes=cfg["refreshMinutes"],
            )
        )
        + "</p></div></details>"
    )
    return panel


def _footer(data: dict, cfg: dict, t: Translator) -> str:
    if data["error"]:
        return (
            f'<div class="sb-tip">{icon("triangle-alert")}<span>'
            f'{escape(t("sp.fetchFailed"))}: {escape(data["error"][:140])}<br>'
            f'<span class="sb-faint">{escape(t("sp.lastSuccess"))}: '
            f'{escape(data["lastOk"] or portfolio.NO_DATA)}</span></span></div>'
        )
    return (
        '<p class="sb-meta">'
        + escape(
            tr(
                t,
                "sp.updated",
                time=data["lastOk"] or portfolio.NO_DATA,
                provider=cfg["provider"],
            )
        )
        + "</p>"
    )


def active_tab(data: dict, cfg: dict) -> str:
    """With nothing tracked the panel opens where the work starts."""
    tab = data["tab"] if data["tab"] in TABS else TABS[0]
    if not data.get("tabChosen") and not cfg["positions"] and not cfg["watchlist"]:
        return "manage"
    return tab


def flyout(data: dict, cfg: dict, t: Translator, lang: str) -> str:
    """The pinned panel: one root element, one width request, three tabs."""
    base = cfg["baseCurrency"]
    rows = [
        portfolio.position_row(position, data["quotes"], base, data["fx"])
        for position in cfg["positions"]
    ]
    sums = portfolio.totals(rows)
    active = active_tab(data, cfg)

    panels = {
        "portfolio": _portfolio_panel(rows, sums, data, cfg, t, lang),
        "watchlist": _watchlist_panel(data, cfg, t, lang),
        "manage": _manage_panel(data, cfg, t, lang),
    }
    counts = {
        "portfolio": len(cfg["positions"]),
        "watchlist": len(cfg["watchlist"]),
        "manage": 0,
    }
    body = ""
    for tab in TABS:
        hidden = "" if tab == active else " hidden"
        body += f'<section data-tab-panel="{tab}"{hidden}>{panels[tab]}</section>'

    notice = ""
    if cfg["provider"] == "finnhub" and not cfg["hasToken"]:
        notice = _alert("warn", t("sp.tokenTitle"), t("sp.tokenHint"), "triangle-alert")
    elif not data["lastOk"] and not data["error"] and cfg["symbols"]:
        notice = _alert("info", t("sp.loading"), t("sp.loadingHint"), "info")

    return (
        '<section data-sb-flyout-width="wide">'
        + _header(t, data["busy"])
        + notice
        + f"<div data-tabs>{_tabs_strip(active, t, counts)}{body}</div>"
        + _footer(data, cfg, t)
        + "</section>"
    )


# ------------------------------------------------------------------ popup


def alert_popup(
    symbol: str,
    move: float,
    old_price: float,
    new_price: float,
    currency: str,
    t: Translator,
    lang: str,
) -> str:
    up = move >= 0
    glyph = "trending-up" if up else "trending-down"
    tone = "sb-ok" if up else "sb-crit"
    return (
        f'<div class="sb-inline"><span class="{tone}">{icon(glyph)}</span>'
        f"<div><b>{escape(symbol)} {escape(portfolio.fmt_percent(move, lang))}</b><br>"
        f'<span class="sb-mono sb-dim">'
        f"{escape(portfolio.fmt_price(old_price, currency, lang))} \u2192 "
        f"{escape(portfolio.fmt_price(new_price, currency, lang))}</span></div>"
        + _button("refresh", t("sp.refresh"), symbol="refresh-cw", icon_only=True)
        + "</div>"
    )
