# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Converter: currencies on the ECB table (Frankfurter, no key) and units.

Endpoints (Frankfurter v2, shapes verified live 2026-09-15; v1 still answers
but carries a Deprecation header pointing to v2):
- https://api.frankfurter.dev/v2/providers/ecb/rates?base=EUR -> a list of
  {date, base, quote, rate} rows, one per ECB currency, the base at 1.0.
- https://api.frankfurter.dev/v2/currencies -> a list of {iso_code, name, ...}.
The table is downloaded once per refreshHours on a thread and cached in
app.data_dir; offline the cached table stays on screen with its date. Cross
rates come from that one table, so the base only decides what is fetched.
The last conversion of each tab lives in state.json, so the flyout reopens
where the user left it. Unit math is units.py, currency math rates.py.
"""

import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import rates as fx
import units
import views
from smabar_sdk import Plugin, RpcError

app = Plugin()

TILE = "convert"
API = "https://api.frankfurter.dev/v2"
# Cloudflare in front of the API answers urllib's default agent with 403.
USER_AGENT = "smabar-converter/1.0"
TICK_SECONDS = 600
CACHE_FILE = "rates.json"
STATE_FILE = "state.json"
DEFAULTS = {"baseCurrency": "EUR", "favoritePair": "EUR/USD", "decimals": 2, "refreshHours": 12}
DEFAULT_PAIR = ("EUR", "USD")
UNIT_DEFAULTS = {"length": ("km", "mi"), "mass": ("kg", "lb"), "temperature": ("°C", "°F"),
                 "area": ("m²", "ft²"), "volume": ("l", "gal"), "speed": ("km/h", "mph"), "data": ("GB", "GiB")}
FETCH_ERRORS = (OSError, ValueError, TypeError)  # URLError, HTTPError and JSONDecodeError included
NUMBER = int | float

# The ECB table and its predecessor; the worker thread replaces it under the lock.
cache: dict = {"fetchedAt": 0.0, "date": "", "base": "", "rates": {}, "currencies": {}, "previous": None}
# What the flyout shows: the active tab and the last inputs of each tab.
state: dict = {"tab": "currency", "last": "",
               "currency": {"amount": 100.0, "from": "EUR", "to": "USD"},
               "units": {"category": "length", "amount": 1.0, "from": "km", "to": "mi"}}
status: dict = {"busy": False, "error": "", "invalid": {"currency": False, "units": False}}
cfg: dict = {"base": "EUR", "pair": DEFAULT_PAIR, "decimals": 2, "hours": 12.0}
lock = threading.Lock()


# --- settings ------------------------------------------------------------


def number_setting(settings: dict, key: str, low: float, high: float) -> float:
    try:
        value = float(settings.get(key, DEFAULTS[key]))
    except (TypeError, ValueError):
        value = math.nan
    if not low <= value <= high:
        app.log("warn", f"{key} must be between {low:g} and {high:g}; using {DEFAULTS[key]}", value=str(settings.get(key)))
        return float(DEFAULTS[key])
    return value


def apply_settings(settings: dict) -> None:
    """Resolve the settings once; a bad value falls back with one warning."""
    base = str(settings.get("baseCurrency", DEFAULTS["baseCurrency"])).strip().upper()
    if not fx.CODE.fullmatch(base):
        app.log("warn", "baseCurrency is not a three-letter code; using EUR", value=base)
        base = "EUR"
    pair = fx.parse_pair(str(settings.get("favoritePair", DEFAULTS["favoritePair"])))
    if pair is None:
        app.log("warn", "favoritePair is not FROM/TO; showing EUR/USD", value=str(settings.get("favoritePair")))
        pair = DEFAULT_PAIR
    cfg.update(base=base, pair=pair, decimals=int(number_setting(settings, "decimals", 0, 10)),
               hours=number_setting(settings, "refreshHours", 1, 168))
    check_pair()


def check_pair() -> None:
    """The favourite pair must be on the ECB table; otherwise the tile shows EUR/USD."""
    with lock:
        table = cache["rates"]
    if table and cfg["pair"] != DEFAULT_PAIR and any(code not in table for code in cfg["pair"]):
        app.log("warn", "favoritePair is not on the ECB table; showing EUR/USD",
                pair="/".join(cfg["pair"]), available=", ".join(sorted(table)))
        cfg["pair"] = DEFAULT_PAIR


# --- files ---------------------------------------------------------------


def read_json(name: str) -> dict:
    try:
        data = json.loads((app.data_dir / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        app.log("warn", f"ignoring an unreadable {name}", error=str(error), hint="the next write replaces it")
        return {}
    return data if isinstance(data, dict) else {}


def write_json(name: str, data: dict) -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    path = app.data_dir / name
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        app.log("warn", f"could not write {name}", error=str(error))


def table_of(raw: object) -> dict[str, float] | None:
    """A cached rates table, or None when the shape is not code -> positive number."""
    if not isinstance(raw, dict) or not raw:
        return None
    if any(not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, NUMBER) or v <= 0 for k, v in raw.items()):
        return None
    return {code: float(rate) for code, rate in raw.items()}


def load_cache() -> None:
    data = read_json(CACHE_FILE)
    table = table_of(data.get("rates"))
    if table is None:
        return
    names = data.get("currencies")
    previous = data.get("previous")
    previous_table = table_of(previous.get("rates")) if isinstance(previous, dict) else None
    fetched = data.get("fetchedAt")
    with lock:
        cache.update(
            fetchedAt=float(fetched) if isinstance(fetched, NUMBER) else 0.0,
            date=str(data.get("date", "")), base=str(data.get("base", "")), rates=table,
            currencies={str(k): str(v) for k, v in names.items()} if isinstance(names, dict) else {},
            previous={"date": str(previous["date"]), "rates": previous_table}
            if previous_table and isinstance(previous.get("date"), str) else None,
        )


def save_cache() -> None:
    with lock:
        snapshot = dict(cache)
    write_json(CACHE_FILE, snapshot)


def parse_amount(raw: object) -> float | None:
    """A non-negative finite number from a form field; None otherwise."""
    if isinstance(raw, bool):
        return None
    try:
        number = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def load_state() -> None:
    data = read_json(STATE_FILE)
    if data.get("tab") in views.TABS:
        state["tab"] = data["tab"]
    if data.get("last") in views.TABS:
        state["last"] = data["last"]
    currency = data.get("currency")
    if isinstance(currency, dict):
        amount = parse_amount(currency.get("amount"))
        codes = [str(currency.get(key, "")).upper() for key in ("from", "to")]
        if amount is not None and all(fx.CODE.fullmatch(code) for code in codes):
            state["currency"].update(amount=amount, **{"from": codes[0], "to": codes[1]})
    unit = data.get("units")
    if isinstance(unit, dict) and unit.get("category") in units.CATEGORY_ORDER:
        amount = parse_amount(unit.get("amount"))
        symbols = [units.find_unit(str(unit.get(key, ""))) for key in ("from", "to")]
        if amount is not None and all(s and units.category_of(s) == unit["category"] for s in symbols):
            state["units"].update(category=unit["category"], amount=amount, **{"from": symbols[0], "to": symbols[1]})


def save_state() -> None:
    write_json(STATE_FILE, state)


# --- fetching ------------------------------------------------------------


def get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def download(base: str) -> tuple[str, dict[str, float], dict[str, str]]:
    query = urllib.parse.urlencode({"base": base})
    date, table = fx.parse_rates(get_json(f"{API}/providers/ecb/rates?{query}"), base)
    names = fx.parse_currencies(get_json(f"{API}/currencies"))
    return date, table, names


def refresh() -> None:
    """Worker thread: downloads the table; on failure the cached one stays."""
    base = cfg["base"]
    try:
        try:
            date, table, names = download(base)
        except urllib.error.HTTPError as error:
            if base == "EUR" or error.code >= 500:
                raise
            app.log("warn", "baseCurrency is not an ECB currency; fetching the EUR table", base=base, status=error.code)
            base = "EUR"
            date, table, names = download(base)
    except FETCH_ERRORS as error:
        message = f"{type(error).__name__}: {error}"
        with lock:
            changed = message != status["error"]
            status.update(busy=False, error=message)
        if changed:
            app.log("warn", "rates download failed; showing the cached table", error=message,
                    hint="check the connection; the next try is in 10 minutes")
        render()
        return
    with lock:
        if cache["date"] and date > cache["date"]:
            cache["previous"] = {"date": cache["date"], "rates": cache["rates"]}
        cache.update(fetchedAt=time.time(), date=date, base=base, rates=table,
                     currencies={code: names.get(code, "") for code in table})
        status.update(busy=False, error="")
    save_cache()
    check_pair()
    app.log("info", "rates updated", base=base, date=date, currencies=len(table))
    render()


def start_fetch() -> None:
    """Starts one download; a request while one runs is folded in."""
    with lock:
        if status["busy"]:
            return
        status["busy"] = True
    threading.Thread(target=refresh, daemon=True).start()


# --- rendering -----------------------------------------------------------


def currency_model(table: dict, names: dict, entry: dict, invalid: bool, cached: bool, date: str) -> dict:
    src, dst = entry["from"], entry["to"]
    rate = fx.cross_rate(table, src, dst) if src in table and dst in table else None
    codes = sorted(table) if table else sorted({src, dst})
    return {"amount": entry["amount"], "src": src, "dst": dst, "rate": rate, "date": date,
            "value": None if rate is None else entry["amount"] * rate, "invalid": invalid,
            "available": bool(table), "cached": cached,
            "options": [(code, f"{code} · {names[code]}" if names.get(code) else code) for code in codes]}


def units_model(entry: dict, invalid: bool, decimals: int) -> dict:
    src, dst = entry["from"], entry["to"]
    return {"category": entry["category"], "amount": entry["amount"], "src": src, "dst": dst, "invalid": invalid,
            "value": units.convert(entry["amount"], src, dst), "line": units.rate_line(src, dst, decimals)}


def render() -> None:
    """Push every surface from a snapshot; safe to call from the worker thread."""
    with lock:
        snapshot = dict(cache)
        shown = json.loads(json.dumps(state))
        invalid = dict(status["invalid"])
        cached = bool(status["error"])
    table, decimals = snapshot["rates"], cfg["decimals"]
    pair = cfg["pair"]
    rate = fx.cross_rate(table, *pair) if all(code in table for code in pair) else None
    change = None
    if snapshot["previous"] is not None:
        percent = fx.change_percent(table, snapshot["previous"]["rates"], *pair)
        change = None if percent is None else (percent, snapshot["previous"]["date"])
    currency = currency_model(table, snapshot["currencies"], shown["currency"], invalid["currency"], cached, snapshot["date"])
    unit = units_model(shown["units"], invalid["units"], decimals)
    app.render(TILE, "tile", views.tile(pair, rate, change, snapshot["date"], app.t))
    app.render(TILE, "hover", views.hover(views.summary(shown["last"], currency, unit, decimals), app.t))
    app.render(TILE, "flyout", views.flyout(shown["tab"], currency, unit, decimals, app.t))


# --- lifecycle -----------------------------------------------------------


@app.on_ready
def ready() -> None:
    """Cache first, so the bar shows rates before the first download."""
    load_cache()
    load_state()
    apply_settings(app.settings)
    render()


@app.every(TICK_SECONDS)
def tick() -> None:
    with lock:
        due = not cache["rates"] or time.time() - cache["fetchedAt"] >= cfg["hours"] * 3600
    if due:
        start_fetch()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    apply_settings(settings)
    render()
    with lock:
        base_changed = cfg["base"] != cache["base"]
    if base_changed:
        start_fetch()


# --- actions -------------------------------------------------------------


def currency_code(raw: object, table: dict) -> str | None:
    code = str(raw or "").strip().upper()
    if not fx.CODE.fullmatch(code) or (table and code not in table):
        return None
    return code


def update_currency(fields: dict, swap: bool) -> None:
    entry = state["currency"]
    with lock:
        table = cache["rates"]
    amount = parse_amount(fields.get("cv-amount", entry["amount"]))
    src = currency_code(fields.get("cv-from"), table) or entry["from"]
    dst = currency_code(fields.get("cv-to"), table) or entry["to"]
    if swap:
        src, dst = dst, src
    entry.update({"from": src, "to": dst})
    status["invalid"]["currency"] = amount is None
    if amount is not None:
        entry["amount"] = amount
        state["last"] = "currency"


def update_units(fields: dict, swap: bool) -> None:
    entry = state["units"]
    amount = parse_amount(fields.get("un-amount", entry["amount"]))
    symbols = []
    for key, current in (("un-from", entry["from"]), ("un-to", entry["to"])):
        unit = units.find_unit(str(fields.get(key, "")))
        symbols.append(unit if unit and units.category_of(unit) == entry["category"] else current)
    src, dst = symbols
    if swap:
        src, dst = dst, src
    entry.update({"from": src, "to": dst})
    status["invalid"]["units"] = amount is None
    if amount is not None:
        entry["amount"] = amount
        state["last"] = "units"


def set_category(category: str, fields: dict) -> None:
    entry = state["units"]
    if category != entry["category"]:
        src, dst = UNIT_DEFAULTS[category]
        entry.update({"category": category, "from": src, "to": dst})
    amount = parse_amount(fields.get("un-amount", entry["amount"]))
    if amount is not None:
        entry["amount"] = amount


@app.on_action(TILE)
def on_action(name: str, value: object) -> None:
    """Form submits deliver every data-field of the flyout as a dict. Names this
    plugin did not register (the shell's own "tile" click, say) are ignored."""
    fields = value if isinstance(value, dict) else {}
    if name == "refresh":
        start_fetch()
        return
    if name == "tab":
        if value not in views.TABS:
            return
        state["tab"] = value
    elif name.startswith("category:") and name[9:] in units.CATEGORY_ORDER:
        set_category(name[9:], fields)
    elif name in ("convert-currency", "swap-currency"):
        update_currency(fields, swap=name == "swap-currency")
    elif name in ("convert-units", "swap-units"):
        update_units(fields, swap=name == "swap-units")
    else:
        return
    save_state()
    render()


# --- agent commands ------------------------------------------------------


def finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, NUMBER) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def text_argument(arguments: dict, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string: a currency code such as USD or a unit such as km")
    return value.strip()


CONVERT_INPUT = {
    "type": "object",
    "properties": {
        "amount": {"type": "number", "description": "The quantity to convert"},
        "from": {"type": "string", "description": "Currency code (USD) or unit symbol (km, kg, °C or C, m2, fl oz, km/h, GiB)"},
        "to": {"type": "string", "description": "Currency code or unit symbol of the same category"},
    },
    "required": ["amount", "from", "to"],
    "additionalProperties": False,
}
CONVERT_OUTPUT = {
    "type": "object",
    "properties": {
        "kind": {"enum": ["currency", "unit"]},
        "amount": {"type": "number"},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "value": {"type": "number", "description": "amount expressed in `to`"},
        "rate": {"type": "number", "description": "How many `to` one `from` is (the slope for temperature)"},
        "line": {"type": "string", "description": "The rate or formula as text"},
        "date": {"type": "string", "description": "ECB reference date of the rate (currency only)"},
        "category": {"type": "string", "description": "Unit category (unit only)"},
    },
    "required": ["kind", "amount", "from", "to", "value", "rate", "line"],
}
RATES_OUTPUT = {
    "type": "object",
    "properties": {
        "base": {"type": "string"},
        "date": {"type": "string", "description": "ECB reference date"},
        "rates": {"type": "object", "additionalProperties": {"type": "number"}},
    },
    "required": ["base", "date", "rates"],
}


@app.command("convert",
             description="Convert an amount between two currencies of the ECB table (ISO codes) or two units of one "
                         "category: length, mass, temperature, area, volume, speed, data. Returns the value and the "
                         "rate or factor used.",
             input_schema=CONVERT_INPUT, output_schema=CONVERT_OUTPUT)
def cmd_convert(arguments: dict) -> dict:
    amount = finite_number(arguments.get("amount"), "amount")
    src, dst = text_argument(arguments, "from"), text_argument(arguments, "to")
    with lock:
        table, date = dict(cache["rates"]), cache["date"]
    codes = (src.upper(), dst.upper())
    if all(code in table for code in codes):
        rate = fx.cross_rate(table, *codes)
        line = views.tr(app.t, "convert.rateLine", src=codes[0], rate=units.fmt(rate, 4), dst=codes[1], date=date)
        return {"kind": "currency", "amount": amount, "from": codes[0], "to": codes[1],
                "value": amount * rate, "rate": rate, "line": line, "date": date}
    symbols = (units.find_unit(src), units.find_unit(dst))
    if None in symbols:
        known = ", ".join(sorted(table)) if table else "none cached yet"
        raise ValueError(f"unknown currency or unit in {src!r} -> {dst!r}; currencies: {known}; "
                         f"units: {', '.join(units.all_units())}")
    value = units.convert(amount, *symbols)
    slope = round(units.convert(1, *symbols) - units.convert(0, *symbols), 12)
    return {"kind": "unit", "category": units.category_of(symbols[0]), "amount": amount,
            "from": symbols[0], "to": symbols[1], "value": value, "rate": slope,
            "line": units.rate_line(symbols[0], symbols[1], cfg["decimals"])}


@app.command("rates", description="The cached ECB table: base currency, reference date and the rate of every currency.",
             input_schema={"type": "object", "properties": {}, "additionalProperties": False},
             output_schema=RATES_OUTPUT)
def cmd_rates(arguments: dict) -> dict:
    with lock:
        snapshot = dict(cache)
    if not snapshot["rates"]:
        raise RpcError(-32001, "rates unavailable: no ECB table cached yet; check the connection and retry")
    return {"base": snapshot["base"], "date": snapshot["date"], "rates": snapshot["rates"]}


if __name__ == "__main__":
    app.run()
