"""Portfolio maths, settings validation and formatting.

Nothing here imports the SDK or touches the network, so this module can be
read, reasoned about and unit-tested without a running bar. plugin.py owns
the state and the RPC, views.py owns the markup, providers.py owns the HTTP.
"""

from __future__ import annotations

import math

NO_DATA = "\u2013"

CURRENCY_SIGNS = {
    "EUR": "\u20ac",
    "USD": "$",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "CHF": "CHF",
    "CAD": "C$",
    "AUD": "A$",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "PLN": "z\u0142",
}
PREFIX_SIGNS = ("$", "\u00a3", "\u00a5", "C$", "A$")

MAX_SYMBOLS = 25
MAX_SYMBOL_LEN = 24


def is_number(value: object) -> bool:
    """True for a finite int/float that is not a bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def clean_symbol(value: object) -> str:
    """Provider symbols are short and printable; anything else is dropped."""
    symbol = str(value or "").strip().upper()
    if not symbol or len(symbol) > MAX_SYMBOL_LEN:
        return ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.^-=:&")
    return symbol if set(symbol) <= allowed else ""


def normalize_positions(raw: object) -> list[dict]:
    """Validates the `positions` setting; invalid entries are skipped."""
    if not isinstance(raw, list):
        return []
    positions: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        symbol = clean_symbol(entry.get("symbol"))
        shares = entry.get("shares")
        if not symbol or symbol in seen or not is_number(shares) or float(shares) <= 0:
            continue
        buy = entry.get("buyPrice", 0)
        positions.append(
            {
                "symbol": symbol,
                "shares": float(shares),
                "buyPrice": float(buy) if is_number(buy) and float(buy) > 0 else 0.0,
            }
        )
        seen.add(symbol)
        if len(positions) >= MAX_SYMBOLS:
            break
    return positions


def normalize_watchlist(raw: object, exclude: list[str] | None = None) -> list[str]:
    """Validates the `watchlist` setting; held symbols are not repeated."""
    if isinstance(raw, str):
        raw = [part for part in raw.split(",")]
    if not isinstance(raw, list):
        return []
    blocked = set(exclude or [])
    result: list[str] = []
    for entry in raw:
        symbol = clean_symbol(entry)
        if symbol and symbol not in blocked and symbol not in result:
            result.append(symbol)
        if len(result) >= MAX_SYMBOLS:
            break
    return result


def tracked_symbols(positions: list[dict], watchlist: list[str]) -> list[str]:
    """Every symbol that needs a quote, holdings first, without duplicates."""
    symbols = [position["symbol"] for position in positions]
    for symbol in watchlist:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols[:MAX_SYMBOLS]


def convert(amount: float, currency: str, base: str, fx: dict) -> float | None:
    """Amount in `currency` expressed in `base`; None when no rate is known."""
    if not is_number(amount):
        return None
    if not currency or currency == base:
        return float(amount)
    rate = fx.get(currency)
    if not is_number(rate) or float(rate) <= 0:
        return None
    return float(amount) * float(rate)


def quote_change(quote: dict) -> tuple[float | None, float | None]:
    """Absolute and percentage move since the previous close."""
    price, previous = quote.get("price"), quote.get("prev")
    if not is_number(price) or not is_number(previous) or float(previous) <= 0:
        return None, None
    absolute = float(price) - float(previous)
    return absolute, absolute / float(previous) * 100.0


def position_row(position: dict, quotes: dict, base: str, fx: dict) -> dict:
    """One table row: current value, day move and total gain, all in `base`.

    Every derived number is optional on purpose: a quote can be missing, a
    currency can have no FX rate and a holding can have no purchase price.
    The view renders a placeholder instead of hiding the position.
    """
    symbol = position["symbol"]
    quote = quotes.get(symbol) or {}
    currency = str(quote.get("currency") or "")
    price = quote.get("price")
    shares = position["shares"]
    row = {
        "symbol": symbol,
        "name": str(quote.get("name") or symbol),
        "shares": shares,
        "buyPrice": position["buyPrice"],
        "currency": currency,
        "price": float(price) if is_number(price) else None,
        "value": None,
        "dayAbs": None,
        "dayPct": None,
        "gainAbs": None,
        "gainPct": None,
        "converted": True,
        "hasQuote": is_number(price),
    }
    if not row["hasQuote"]:
        return row
    value = convert(shares * row["price"], currency, base, fx)
    if value is None:
        row["converted"] = False
        return row
    row["value"] = value
    day_abs, day_pct = quote_change(quote)
    if day_abs is not None:
        row["dayAbs"] = convert(shares * day_abs, currency, base, fx)
        row["dayPct"] = day_pct
    if position["buyPrice"] > 0:
        cost = convert(shares * position["buyPrice"], currency, base, fx)
        if cost is not None and cost > 0:
            row["gainAbs"] = value - cost
            row["gainPct"] = (value - cost) / cost * 100.0
    return row


def totals(rows: list[dict]) -> dict:
    """Portfolio sums over the rows that could be valued and converted."""
    value = 0.0
    day_abs = 0.0
    gain_abs = 0.0
    cost = 0.0
    valued = 0
    unpriced: list[str] = []
    unconverted: list[str] = []
    for row in rows:
        if not row["hasQuote"]:
            unpriced.append(row["symbol"])
            continue
        if row["value"] is None:
            unconverted.append(row["symbol"])
            continue
        value += row["value"]
        valued += 1
        if row["dayAbs"] is not None:
            day_abs += row["dayAbs"]
        if row["gainAbs"] is not None:
            gain_abs += row["gainAbs"]
            cost += row["value"] - row["gainAbs"]
    previous = value - day_abs
    return {
        "value": value if valued else None,
        "dayAbs": day_abs if valued else None,
        "dayPct": (day_abs / previous * 100.0) if valued and previous > 0 else None,
        "gainAbs": gain_abs if cost > 0 else None,
        "gainPct": (gain_abs / cost * 100.0) if cost > 0 else None,
        "cost": cost if cost > 0 else None,
        "valued": valued,
        "unpriced": unpriced,
        "unconverted": unconverted,
    }


def top_mover(rows: list[dict]) -> dict | None:
    """The holding with the largest day move in either direction."""
    moved = [row for row in rows if row["dayPct"] is not None]
    return max(moved, key=lambda row: abs(row["dayPct"])) if moved else None


def currencies_of(symbols: list[str], quotes: dict) -> list[str]:
    """Distinct quote currencies of the tracked symbols, for the FX lookup."""
    found: list[str] = []
    for symbol in symbols:
        currency = str((quotes.get(symbol) or {}).get("currency") or "")
        if currency and currency not in found:
            found.append(currency)
    return found


# ---------------------------------------------------------------- formatting


def _decimal_style(lang: str) -> bool:
    """True when this UI language writes 1.234,56 instead of 1,234.56."""
    return str(lang or "en").lower().startswith("de")


def fmt_number(
    value: float, lang: str = "en", decimals: int = 2, group: bool = True
) -> str:
    if not is_number(value):
        return NO_DATA
    text = f"{value:,.{decimals}f}" if group else f"{value:.{decimals}f}"
    if _decimal_style(lang):
        text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return text


def fmt_money(
    value: float,
    currency: str,
    lang: str = "en",
    decimals: int = 2,
    group: bool = True,
) -> str:
    """Money in the reader's number style; unknown codes print as a suffix."""
    if not is_number(value):
        return NO_DATA
    number = fmt_number(value, lang, decimals, group)
    sign = CURRENCY_SIGNS.get(str(currency or "").upper())
    if not sign:
        return f"{number} {str(currency or '').upper()}".strip()
    if _decimal_style(lang) or sign not in PREFIX_SIGNS:
        return f"{number}\u00a0{sign}"
    return f"{sign}{number}"


def fmt_money_compact(value: float, currency: str, lang: str = "en") -> str:
    """Tile money: drops the cents once the number gets long."""
    if not is_number(value):
        return NO_DATA
    decimals = 0 if abs(value) >= 10000 else 2
    return fmt_money(value, currency, lang, decimals)


def fmt_price(value: float, currency: str, lang: str = "en") -> str:
    """Quote price: more decimals for penny stocks, fewer for index levels."""
    if not is_number(value):
        return NO_DATA
    decimals = 4 if abs(value) < 1 else 2
    return fmt_money(value, currency, lang, decimals)


def fmt_percent(value: float, lang: str = "en", decimals: int = 2) -> str:
    if not is_number(value):
        return NO_DATA
    number = fmt_number(abs(value), lang, decimals, group=False)
    sign = "+" if value >= 0 else "\u2212"
    return f"{sign}{number}\u00a0%"


def fmt_shares(value: float, lang: str = "en") -> str:
    if not is_number(value):
        return NO_DATA
    decimals = 0 if float(value).is_integer() else 4
    return fmt_number(value, lang, decimals)


def fmt_signed_money(
    value: float, currency: str, lang: str = "en", compact: bool = False
) -> str:
    """Money with an explicit sign, like fmt_percent: "+38.12 €", "−38.12 €"."""
    if not is_number(value):
        return NO_DATA
    amount = abs(float(value))
    text = (
        fmt_money_compact(amount, currency, lang)
        if compact
        else fmt_money(amount, currency, lang)
    )
    return ("+" if value >= 0 else "\u2212") + text


def initials(symbol: str) -> str:
    """Two characters for an avatar: AAPL -> AA, ^GDAXI -> GD, SAP.DE -> SA."""
    letters = [char for char in str(symbol or "") if char.isalnum()]
    return "".join(letters[:2]).upper() or "?"


def spark_points(points: list, limit: int = 40) -> str:
    """Comma-separated sparkline data; empty when fewer than two points."""
    usable = [float(point) for point in (points or []) if is_number(point)]
    if len(usable) < 2:
        return ""
    return ",".join(f"{point:.6g}" for point in usable[-limit:])
