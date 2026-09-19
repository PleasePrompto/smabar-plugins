# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Stock portfolio tile: holdings value, day change and a live watchlist.

Layout of the plugin:
  plugin.py     - this file: lifecycle, state, threads, actions, cache
  providers.py  - the HTTP quote sources (Yahoo chart endpoint / Finnhub)
  portfolio.py  - validation, portfolio maths and formatting (no I/O)
  views.py      - the markup for tile, hover, flyout and popup (no I/O)
  locales/      - en.json and de.json

Principles followed from the plugin guide:
  * The first render happens in on_ready, from the cache in app.data_dir, so
    the bar shows the last known value before the network is touched.
  * Handlers share ONE lock, so every request runs on a worker thread and only
    publishes its result back into `state`; a failed update keeps the previous
    prices on screen instead of blanking the tile.
  * Everything writable lives in app.data_dir and is written tmp + os.replace.
  * No credentials are bundled: the optional Finnhub key is read from
    <data_dir>/finnhub_token.txt, a file the user creates.
"""

import json
import os
import threading
import time
from datetime import datetime

import portfolio
import providers
import views
from smabar_sdk import Plugin

app = Plugin()

TILE = "portfolio"
CACHE_FILE = "market.json"
TOKEN_FILE = "finnhub_token.txt"
CACHE_KEYS = ("quotes", "fx", "series", "history", "lastOk", "alertBase")
HISTORY_MAX = 60
SERIES_MAX = 60
MIN_REFRESH_MINUTES = 1.0
TICK_SECONDS = 60.0
REQUEST_PAUSE = 0.25

# Everything the surfaces read. The worker thread and the handlers both write
# it under `lock`; every render takes a snapshot first.
state: dict = {
    "quotes": {},  # symbol -> {symbol,name,price,prev,currency,exchange,points}
    "fx": {},  # currency -> rate into the base currency
    "series": {},  # symbol -> polled prices, the fallback sparkline
    "history": [],  # portfolio total per successful poll
    "alertBase": {},  # symbol -> price at its last alert
    "lastOk": "",
    "error": "",
    "busy": False,
    "tab": "portfolio",
    "tabChosen": False,  # until the user picks one, an empty plugin opens on "Add"
    "query": "",
    "results": [],
    "searching": False,  # a lookup is running; the view shows placeholders
    "formError": "",
    "positionError": "",
    "positionOk": "",
    "draft": {"symbol": "", "name": "", "shares": "", "buyPrice": "", "editing": False},
    "applied": None,  # our own last settings write, to ignore its echo
    "nextPoll": 0.0,
}
lock = threading.Lock()


# --------------------------------------------------------------- settings


def token() -> str:
    """The optional Finnhub key, from a file the USER creates. Never bundled."""
    try:
        return (app.data_dir / TOKEN_FILE).read_text(encoding="utf-8").strip()[:128]
    except (OSError, UnicodeDecodeError):
        return ""


def config() -> dict:
    """A validated snapshot of the settings; bad values fall back, never crash."""
    settings = app.settings if isinstance(app.settings, dict) else {}
    positions = portfolio.normalize_positions(settings.get("positions"))
    held = [position["symbol"] for position in positions]
    watchlist = portfolio.normalize_watchlist(settings.get("watchlist"), exclude=held)
    base = portfolio.clean_symbol(settings.get("baseCurrency") or "EUR") or "EUR"
    provider = settings.get("provider")
    if provider not in ("yahoo", "finnhub"):
        provider = "yahoo"
    layout = settings.get("coverLayout")
    if layout not in views.LAYOUTS:
        layout = views.LAYOUTS[0]
    try:
        minutes = max(MIN_REFRESH_MINUTES, float(settings.get("refreshMinutes", 5)))
    except (TypeError, ValueError):
        app.log("warn", 'settings key "refreshMinutes" is not a number; using 5')
        minutes = 5.0
    try:
        alert = float(settings.get("alertPercent", 0))
    except (TypeError, ValueError):
        app.log("warn", 'settings key "alertPercent" is not a number; alerts are off')
        alert = 0.0
    return {
        "positions": positions,
        "watchlist": watchlist,
        "symbols": portfolio.tracked_symbols(positions, watchlist),
        "baseCurrency": base[:8],
        "provider": provider,
        "refreshMinutes": minutes,
        "alertPercent": alert,
        "coverLayout": layout,
        "tileRotate": bool(settings.get("tileRotate", True)),
        "hasToken": bool(token()),
    }


def write_settings(changes: dict) -> None:
    """set_settings REPLACES the whole object, so spread the current one."""
    merged = {**(app.settings if isinstance(app.settings, dict) else {}), **changes}
    with lock:
        state["applied"] = json.dumps(merged, sort_keys=True, default=str)
    app.set_settings(merged)


# ------------------------------------------------------------------ cache


def _valid_quote(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("symbol"), str) or not value["symbol"]:
        return False
    if not portfolio.is_number(value.get("price")):
        return False
    points = value.get("points")
    return isinstance(points, list) and all(
        portfolio.is_number(point) for point in points
    )


def _valid_numbers(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and portfolio.is_number(number)
        for key, number in value.items()
    )


def _valid_series(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(points, list)
        and all(portfolio.is_number(point) for point in points)
        for key, points in value.items()
    )


def load_cache() -> bool:
    """Restores the last known market data. True when something was restored."""
    path = app.data_dir / CACHE_FILE
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError, ValueError) as error:
        app.log(
            "warn",
            "ignoring an unreadable price cache; starting without cached prices",
            error=f"{type(error).__name__}: {error}",
            hint=f"delete {path.name}; the next successful update rewrites it",
        )
        return False
    if not isinstance(cached, dict) or not all(key in cached for key in CACHE_KEYS):
        app.log("warn", "price cache is incomplete; starting without cached prices")
        return False
    quotes = cached["quotes"]
    if not isinstance(quotes, dict) or not all(
        _valid_quote(quote) for quote in quotes.values()
    ):
        app.log("warn", "price cache holds invalid quotes; ignoring it")
        return False
    if not (
        _valid_numbers(cached["fx"])
        and _valid_series(cached["series"])
        and isinstance(cached["history"], list)
        and all(portfolio.is_number(point) for point in cached["history"])
        and isinstance(cached["lastOk"], str)
        and _valid_numbers(cached["alertBase"])
    ):
        app.log("warn", "price cache holds invalid data; ignoring it")
        return False
    with lock:
        state.update({key: cached[key] for key in CACHE_KEYS})
    return bool(quotes)


def save_cache() -> None:
    """Write beside the final name, then swap: no half-written cache survives."""
    with lock:
        snapshot = {key: state[key] for key in CACHE_KEYS}
    path = app.data_dir / CACHE_FILE
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(snapshot), encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as error:
        app.log("warn", "could not cache the market data", error=str(error))


# --------------------------------------------------------------- rendering


def snapshot() -> dict:
    with lock:
        return {
            "quotes": dict(state["quotes"]),
            "fx": dict(state["fx"]),
            "series": {key: list(value) for key, value in state["series"].items()},
            "history": list(state["history"]),
            "lastOk": state["lastOk"],
            "error": state["error"],
            "busy": state["busy"],
            "tab": state["tab"],
            "tabChosen": state["tabChosen"],
            "query": state["query"],
            "results": list(state["results"]),
            "searching": state["searching"],
            "formError": state["formError"],
            "positionError": state["positionError"],
            "positionOk": state["positionOk"],
            "draft": dict(state["draft"]),
        }


def render_all() -> None:
    """Pushes every surface. app.render is thread-safe, so the worker may call it."""
    data = snapshot()
    cfg = config()
    language = app.language or "en"
    app.render(TILE, "tile", views.tile(data, cfg, app.t, language))
    app.render(TILE, "hover", views.hover(data, cfg, app.t, language))
    app.render(TILE, "flyout", views.flyout(data, cfg, app.t, language))


# ----------------------------------------------------------------- fetching


def fetch(cfg: dict) -> None:
    """Worker thread: one request per symbol, then the FX rates, then render."""
    quotes: dict[str, dict] = {}
    failures: list[str] = []
    last_error = ""
    for symbol in cfg["symbols"]:
        try:
            quotes[symbol] = providers.quote(symbol, cfg["provider"], token())
        except providers.ProviderError as error:
            failures.append(symbol)
            last_error = str(error)
            app.log(
                "warn",
                "quote fetch failed; keeping the last known price",
                symbol=symbol,
                provider=cfg["provider"],
                error=str(error)[:200],
                hint="check the symbol and the network; HTTP 429 means the "
                "provider's rate limit was hit - raise refreshMinutes",
            )
        time.sleep(REQUEST_PAUSE)

    rates: dict = {cfg["baseCurrency"]: 1.0}
    unpriced_currencies: list[str] = []
    if quotes:
        wanted = portfolio.currencies_of(list(quotes), quotes)
        rates, unpriced_currencies = providers.fx_rates(
            wanted, cfg["baseCurrency"], cfg["provider"]
        )
        if unpriced_currencies:
            app.log(
                "warn",
                "no exchange rate for a holding's currency; it stays out of the total",
                currencies=",".join(unpriced_currencies),
                base=cfg["baseCurrency"],
                hint="the Finnhub provider has no FX on the free tier; switch the "
                "base currency or the provider",
            )

    alerts: list[tuple] = []
    with lock:
        tracked = set(cfg["symbols"])
        state["quotes"].update(quotes)
        state["quotes"] = {
            symbol: quote
            for symbol, quote in state["quotes"].items()
            if symbol in tracked
        }
        state["fx"] = rates
        for symbol, quote in quotes.items():
            points = state["series"].setdefault(symbol, [])
            points.append(quote["price"])
            del points[:-SERIES_MAX]
        state["series"] = {
            symbol: points
            for symbol, points in state["series"].items()
            if symbol in tracked
        }
        if quotes:
            state["lastOk"] = datetime.now().astimezone().strftime("%H:%M")
            state["error"] = (
                ""
                if not failures
                else f"{', '.join(failures)}: {last_error}"[:200]
            )
        elif cfg["symbols"]:
            state["error"] = last_error or "no quotes"
        else:
            state["error"] = ""
        rows = [
            portfolio.position_row(
                position, state["quotes"], cfg["baseCurrency"], state["fx"]
            )
            for position in cfg["positions"]
        ]
        sums = portfolio.totals(rows)
        if sums["value"] is not None:
            state["history"].append(sums["value"])
            del state["history"][:-HISTORY_MAX]
        alerts = collect_alerts(cfg, quotes)
        state["busy"] = False

    if quotes:
        save_cache()
    for alert in alerts:
        notify(alert, cfg)
    render_all()


def collect_alerts(cfg: dict, quotes: dict) -> list[tuple]:
    """Symbols that moved past the threshold since their last alert.

    Called with `lock` held. The anchor is re-set on every alert, so a slow
    drift still reports once it adds up, and the threshold is the only
    frequency control - the shell does not rate-limit popups.
    """
    threshold = cfg["alertPercent"]
    anchors = state["alertBase"]
    due: list[tuple] = []
    for symbol, quote in quotes.items():
        price = quote.get("price")
        if not portfolio.is_number(price):
            continue
        anchor = anchors.get(symbol)
        if not portfolio.is_number(anchor) or anchor <= 0:
            anchors[symbol] = price
            continue
        if threshold <= 0:
            continue
        move = (price - anchor) / anchor * 100.0
        if abs(move) < threshold:
            continue
        anchors[symbol] = price
        due.append((symbol, move, anchor, price, quote.get("currency", "")))
    tracked = set(cfg["symbols"])
    state["alertBase"] = {
        symbol: price for symbol, price in anchors.items() if symbol in tracked
    }
    return due


def notify(alert: tuple, cfg: dict) -> None:
    """A toast per moved symbol; acceptance is not the same as being shown."""
    symbol, move, anchor, price, currency = alert
    html = views.alert_popup(
        symbol, move, anchor, price, currency, app.t, app.language or "en"
    )
    try:
        if "popups" in getattr(app, "capabilities", frozenset()):
            app.popups.show(TILE, f"move-{symbol}", html, ttl_ms=15000)
        else:
            app.render(TILE, "popup", html, ttl_ms=15000)
    except Exception as error:  # a toast must never take the plugin down
        app.log("warn", "could not deliver the price alert", error=str(error))
        return
    app.log("info", "price alert sent", symbol=symbol, move=f"{move:+.2f}%")


def refresh(reason: str = "") -> None:
    """Starts one update; a second request while one runs is folded into it."""
    cfg = config()
    with lock:
        if state["busy"]:
            return
        state["busy"] = True
        state["nextPoll"] = time.monotonic() + cfg["refreshMinutes"] * 60.0
    if reason:
        app.log("debug", "refreshing quotes", reason=reason, symbols=len(cfg["symbols"]))
    render_all()
    threading.Thread(target=fetch, args=(cfg,), daemon=True).start()


# ---------------------------------------------------------------- lifecycle


@app.on_ready
def ready() -> None:
    """Runs once after initialize: settings and locales exist from here on."""
    if load_cache():
        app.log("info", "restored the cached market data", symbols=len(state["quotes"]))
    render_all()
    refresh("startup")


@app.every(TICK_SECONDS)
def tick() -> None:
    """A one-minute tick; the configured interval decides what actually runs.

    Timers do not run while smabar is stopped, so the deadline is compared
    against the clock rather than counted in ticks.
    """
    with lock:
        due = time.monotonic() >= state["nextPoll"]
    if due:
        refresh("schedule")


# ------------------------------------------------------------------ actions


@app.on_action(TILE, "refresh")
def on_refresh(action: str, value: object) -> None:
    refresh("manual")


@app.on_action(TILE, "select-tab")
def on_select_tab(action: str, value: object) -> None:
    """The shell already switched the panel; remember it so a re-render keeps it."""
    tab = str(value or "")
    if tab in views.TABS:
        with lock:
            state["tab"] = tab
            state["tabChosen"] = True
        render_all()


@app.on_action(TILE, "search")
def on_search(action: str, value: object) -> None:
    fields = value if isinstance(value, dict) else {}
    query = str(fields.get("query", "")).strip()[:64]
    cfg = config()
    with lock:
        state.update(
            {
                "query": query,
                "results": [],
                "searching": bool(query),
                "formError": "",
                "tab": "manage",
                "tabChosen": True,
            }
        )
    if not query:
        render_all()
        return
    threading.Thread(target=run_search, args=(query, cfg), daemon=True).start()
    render_all()


def run_search(query: str, cfg: dict) -> None:
    """Worker thread: the symbol lookup must not block timers or clicks."""
    try:
        results = providers.search(query, cfg["provider"], token())
        error = ""
    except providers.ProviderError as failure:
        results, error = [], f"{app.t('sp.searchFailed')}: {failure}"
        app.log(
            "warn",
            "symbol search failed",
            query=query,
            provider=cfg["provider"],
            error=str(failure)[:200],
        )
    with lock:
        if state["query"] == query:
            state["results"] = results
            state["formError"] = error
            state["searching"] = False
    render_all()


@app.on_action(TILE, "pick")
def on_pick(action: str, value: object) -> None:
    """Puts a searched symbol into the position form instead of adding blindly."""
    symbol = portfolio.clean_symbol(value)
    if not symbol:
        return
    with lock:
        match = next(
            (entry for entry in state["results"] if entry.get("symbol") == symbol), None
        )
        name = str(
            (match or {}).get("name")
            or (state["quotes"].get(symbol) or {}).get("name")
            or ""
        )
        state["draft"] = {
            "symbol": symbol,
            "name": name,
            "shares": "",
            "buyPrice": "",
            "editing": False,
        }
        state["positionError"] = ""
        state["positionOk"] = ""
        state["tab"] = "manage"
        state["tabChosen"] = True
    render_all()


@app.on_action(TILE, "add-watch")
def on_add_watch(action: str, value: object) -> None:
    fields = value if isinstance(value, dict) else {}
    raw = (
        value
        if isinstance(value, str)
        else fields.get("watchSymbol") or fields.get("posSymbol") or ""
    )
    symbol = portfolio.clean_symbol(raw)
    cfg = config()
    if not symbol:
        with lock:
            state["formError"] = app.t("sp.invalidSymbol")
        render_all()
        return
    if symbol in cfg["symbols"]:
        with lock:
            state["formError"] = ""
            state["tab"] = "watchlist"
        render_all()
        return
    with lock:
        state.update(
            {
                "formError": "",
                "query": "",
                "results": [],
                "searching": False,
                "tab": "watchlist",
                "tabChosen": True,
                "positionError": "",
                "positionOk": views.tr(app.t, "sp.watching", symbol=symbol),
                "draft": {
                    "symbol": "",
                    "name": "",
                    "shares": "",
                    "buyPrice": "",
                    "editing": False,
                },
            }
        )
    app.log("info", "watchlist symbol added", symbol=symbol)
    write_settings({"watchlist": [*cfg["watchlist"], symbol]})
    render_all()
    refresh("watchlist changed")


@app.on_action(TILE, "remove-watch")
def on_remove_watch(action: str, value: object) -> None:
    symbol = portfolio.clean_symbol(value)
    cfg = config()
    if symbol not in cfg["watchlist"]:
        return
    app.log("info", "watchlist symbol removed", symbol=symbol)
    write_settings(
        {"watchlist": [entry for entry in cfg["watchlist"] if entry != symbol]}
    )
    with lock:
        state["quotes"].pop(symbol, None)
        state["series"].pop(symbol, None)
    render_all()


@app.on_action(TILE, "edit-position")
def on_edit_position(action: str, value: object) -> None:
    symbol = portfolio.clean_symbol(value)
    position = next(
        (entry for entry in config()["positions"] if entry["symbol"] == symbol), None
    )
    if position is None:
        return
    with lock:
        state["draft"] = {
            "symbol": position["symbol"],
            "name": str((state["quotes"].get(position["symbol"]) or {}).get("name") or ""),
            "shares": portfolio.fmt_number(position["shares"], "en", 4, group=False),
            "buyPrice": (
                portfolio.fmt_number(position["buyPrice"], "en", 4, group=False)
                if position["buyPrice"] > 0
                else ""
            ),
            "editing": True,
        }
        state["positionError"] = ""
        state["positionOk"] = ""
        state["tab"] = "manage"
    render_all()


@app.on_action(TILE, "cancel-edit")
def on_cancel_edit(action: str, value: object) -> None:
    with lock:
        state["draft"] = {
            "symbol": "",
            "name": "",
            "shares": "",
            "buyPrice": "",
            "editing": False,
        }
        state["positionError"] = ""
        state["positionOk"] = ""
    render_all()


def parse_amount(raw: object) -> float | None:
    """Accepts 12.5 and 12,5; returns None for anything that is not positive."""
    text = str(raw or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 and number == number else None


@app.on_action(TILE, "add-position")
def on_add_position(action: str, value: object) -> None:
    """The form's data-field controls arrive as a {name: value} dict."""
    fields = value if isinstance(value, dict) else {}
    symbol = portfolio.clean_symbol(fields.get("posSymbol"))
    shares = parse_amount(fields.get("posShares"))
    raw_buy = str(fields.get("posBuy", "")).strip()
    buy = parse_amount(raw_buy) if raw_buy else 0.0
    if not symbol:
        return fail_position(app.t("sp.invalidSymbol"))
    if shares is None:
        return fail_position(app.t("sp.invalidShares"))
    if raw_buy and buy is None:
        return fail_position(app.t("sp.invalidBuy"))
    cfg = config()
    if (
        len(cfg["positions"]) >= portfolio.MAX_SYMBOLS
        and symbol not in [entry["symbol"] for entry in cfg["positions"]]
    ):
        return fail_position(
            views.tr(app.t, "sp.tooMany", count=portfolio.MAX_SYMBOLS)
        )
    entry = {"symbol": symbol, "shares": shares, "buyPrice": buy or 0.0}
    positions = [
        position for position in cfg["positions"] if position["symbol"] != symbol
    ]
    positions.append(entry)
    changes = {"positions": positions}
    if symbol in cfg["watchlist"]:
        # A held symbol belongs in the table, not twice on the bar.
        changes["watchlist"] = [
            watched for watched in cfg["watchlist"] if watched != symbol
        ]
    with lock:
        state["draft"] = {
            "symbol": "",
            "name": "",
            "shares": "",
            "buyPrice": "",
            "editing": False,
        }
        state["positionError"] = ""
        state["positionOk"] = views.tr(app.t, "sp.savedPosition", symbol=symbol)
        state["query"] = ""
        state["results"] = []
        state["searching"] = False
        state["tab"] = "portfolio"
        state["tabChosen"] = True
    app.log("info", "position saved", symbol=symbol, shares=shares)
    write_settings(changes)
    render_all()
    refresh("positions changed")
    return None


def fail_position(message: str) -> None:
    with lock:
        state["positionError"] = message
        state["positionOk"] = ""
        state["tab"] = "manage"
        state["tabChosen"] = True
    render_all()
    return None


@app.on_action(TILE, "remove-position")
def on_remove_position(action: str, value: object) -> None:
    symbol = portfolio.clean_symbol(value)
    cfg = config()
    if symbol not in [position["symbol"] for position in cfg["positions"]]:
        return
    app.log("info", "position removed", symbol=symbol)
    write_settings(
        {
            "positions": [
                {
                    "symbol": position["symbol"],
                    "shares": position["shares"],
                    "buyPrice": position["buyPrice"],
                }
                for position in cfg["positions"]
                if position["symbol"] != symbol
            ]
        }
    )
    with lock:
        state["quotes"].pop(symbol, None)
        state["series"].pop(symbol, None)
        state["positionOk"] = views.tr(app.t, "sp.removedPosition", symbol=symbol)
        state["positionError"] = ""
    render_all()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    """Runs after every change, including the echo of our own set_settings."""
    with lock:
        echo = json.dumps(settings, sort_keys=True, default=str) == state["applied"]
    if echo:
        return  # the action handler already rendered and refreshed
    with lock:
        state["applied"] = json.dumps(settings, sort_keys=True, default=str)
        state["positionError"] = ""
        state["positionOk"] = ""
    render_all()
    refresh("settings changed")


# ----------------------------------------------------------------- commands

if hasattr(app, "command"):

    @app.command(
        "portfolio_summary",
        description=(
            "Current portfolio total, day change and per-position values in the "
            "configured base currency. Read-only; the numbers are as fresh as "
            "the last successful price update."
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {
                "baseCurrency": {"type": "string"},
                "value": {"type": ["number", "null"]},
                "dayChange": {"type": ["number", "null"]},
                "dayChangePercent": {"type": ["number", "null"]},
                "totalGain": {"type": ["number", "null"]},
                "updatedAt": {"type": "string"},
                "positions": {"type": "array"},
            },
        },
    )
    def portfolio_summary(arguments: dict) -> dict:
        cfg = config()
        data = snapshot()
        rows = [
            portfolio.position_row(
                position, data["quotes"], cfg["baseCurrency"], data["fx"]
            )
            for position in cfg["positions"]
        ]
        sums = portfolio.totals(rows)
        return {
            "baseCurrency": cfg["baseCurrency"],
            "value": sums["value"],
            "dayChange": sums["dayAbs"],
            "dayChangePercent": sums["dayPct"],
            "totalGain": sums["gainAbs"],
            "updatedAt": data["lastOk"],
            "positions": [
                {
                    "symbol": row["symbol"],
                    "shares": row["shares"],
                    "price": row["price"],
                    "currency": row["currency"],
                    "value": row["value"],
                    "dayChangePercent": row["dayPct"],
                    "totalGainPercent": row["gainPct"],
                }
                for row in rows
            ],
        }


if __name__ == "__main__":
    # Guarded so the offline tests can import this module without the RPC loop.
    app.run()
