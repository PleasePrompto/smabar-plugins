"""Quote providers. Plain stdlib HTTP, explicit timeouts, validated results.

Two sources, both chosen so the plugin ships no credentials of its own:

* "yahoo"   - https://query1.finance.yahoo.com/v8/finance/chart/<symbol>
  The endpoint that finance.yahoo.com itself uses. No account, no key. It is
  UNOFFICIAL and undocumented: Yahoo retired its public API in 2017, the older
  /v7/finance/quote answers 401 since January 2026, and the chart endpoint is
  rate limited per IP (community reports: a few requests per second, HTTP 429
  above that). One request per symbol, so the poll interval and the symbol
  limit in portfolio.py are what keep this polite.
* "finnhub" - https://finnhub.io/api/v1 (documented, free key, 60 calls/min)
  GET /quote returns {"c","d","dp","h","l","o","pc","t"}; the free tier has no
  candle history and no FX, so the sparkline is built from polled prices and
  foreign holdings stay unconverted. The key is read from a file the USER
  creates in the plugin's data folder - never from settings, never bundled.

Every function raises ProviderError for an expected failure; the caller keeps
the last good data on screen and logs once.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 12
MAX_BYTES = 2_000_000
MAX_RESULTS = 6
HISTORY_POINTS = 40

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
FINNHUB_BASE = "https://finnhub.io/api/v1"

# Yahoo's JSON hosts answer 429 to the stdlib default agent; the browser agent
# is what the endpoint expects. Documented in the README, not hidden here.
YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

NETWORK_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    TimeoutError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
)


class ProviderError(Exception):
    """An expected, reportable failure of a quote source."""


def _get_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ProviderError(f"HTTP {error.code}") from error
    except NETWORK_ERRORS as error:
        raise ProviderError(str(error) or type(error).__name__) from error
    if len(raw) > MAX_BYTES:
        raise ProviderError("response too large")
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as error:
        raise ProviderError(f"invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ProviderError(f"unexpected response shape: {type(payload).__name__}")
    return payload


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _clip(text: object, limit: int = 80) -> str:
    return str(text or "")[:limit]


# ------------------------------------------------------------------- yahoo


def _yahoo_quote(symbol: str) -> dict:
    query = urllib.parse.urlencode({"range": "1d", "interval": "5m"})
    url = f"{YAHOO_CHART}{urllib.parse.quote(symbol, safe='')}?{query}"
    payload = _get_json(url, YAHOO_HEADERS)
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ProviderError("unexpected chart response")
    error = chart.get("error")
    if isinstance(error, dict) and error:
        raise ProviderError(_clip(error.get("description") or error.get("code")))
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise ProviderError("symbol not found")
    meta = results[0].get("meta") if isinstance(results[0], dict) else None
    if not isinstance(meta, dict):
        raise ProviderError("quote without metadata")

    price = _number(meta.get("regularMarketPrice"))
    # previousClose is only populated for range=1d; chartPreviousClose is the
    # reference before the requested window and is the documented fallback.
    previous = _number(meta.get("previousClose"))
    if previous is None:
        previous = _number(meta.get("chartPreviousClose"))
    currency = str(meta.get("currency") or "").strip()
    points: list[float] = []
    indicators = results[0].get("indicators")
    if isinstance(indicators, dict) and isinstance(indicators.get("quote"), list):
        series = indicators["quote"][0] if indicators["quote"] else {}
        closes = series.get("close") if isinstance(series, dict) else None
        if isinstance(closes, list):
            points = [
                value
                for value in (_number(entry) for entry in closes[-400:])
                if value is not None
            ][-HISTORY_POINTS:]
    if price is None and points:
        price = points[-1]
    if price is None:
        raise ProviderError("no price in the response")

    # London quotes arrive in pence ("GBp"); normalise to pounds so the
    # currency code, the FX lookup and the displayed sign agree.
    if currency == "GBp":
        price /= 100.0
        previous = previous / 100.0 if previous is not None else None
        points = [point / 100.0 for point in points]
        currency = "GBP"

    return {
        "symbol": symbol,
        "name": _clip(
            meta.get("shortName") or meta.get("longName") or symbol, 60
        ).strip()
        or symbol,
        "price": price,
        "prev": previous,
        "currency": currency.upper(),
        "exchange": _clip(meta.get("fullExchangeName") or meta.get("exchangeName"), 40),
        "points": points,
    }


def _yahoo_search(query: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query, "quotesCount": MAX_RESULTS, "newsCount": 0, "listsCount": 0}
    )
    payload = _get_json(f"{YAHOO_SEARCH}?{params}", YAHOO_HEADERS)
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise ProviderError("unexpected search response")
    found: list[dict] = []
    for entry in quotes[: MAX_RESULTS * 2]:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol") or "").strip()
        if not symbol:
            continue
        found.append(
            {
                "symbol": symbol.upper(),
                "name": _clip(
                    entry.get("shortname") or entry.get("longname") or symbol, 60
                ),
                "kind": _clip(entry.get("quoteType"), 16).upper(),
                "exchange": _clip(entry.get("exchDisp") or entry.get("exchange"), 24),
            }
        )
        if len(found) >= MAX_RESULTS:
            break
    return found


def _yahoo_rate(currency: str, base: str) -> float | None:
    """1 unit of `currency` in `base`, via Yahoo's FX pseudo-symbol."""
    quote = _yahoo_quote(f"{currency}{base}=X")
    return quote["price"]


# ----------------------------------------------------------------- finnhub


def _finnhub_quote(symbol: str, token: str) -> dict:
    params = urllib.parse.urlencode({"symbol": symbol, "token": token})
    payload = _get_json(f"{FINNHUB_BASE}/quote?{params}")
    price = _number(payload.get("c"))
    previous = _number(payload.get("pc"))
    if price is None or price == 0:
        raise ProviderError("no price for this symbol")
    return {
        "symbol": symbol,
        "name": symbol,
        "price": price,
        "prev": previous,
        # The free tier covers US listings and reports no currency of its own.
        "currency": "USD",
        "exchange": "",
        "points": [],
    }


def _finnhub_search(query: str, token: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "token": token})
    payload = _get_json(f"{FINNHUB_BASE}/search?{params}")
    results = payload.get("result")
    if not isinstance(results, list):
        raise ProviderError("unexpected search response")
    found: list[dict] = []
    for entry in results[: MAX_RESULTS * 2]:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol") or "").strip()
        if not symbol:
            continue
        found.append(
            {
                "symbol": symbol.upper(),
                "name": _clip(entry.get("description") or symbol, 60),
                "kind": _clip(entry.get("type"), 16).upper(),
                "exchange": "",
            }
        )
        if len(found) >= MAX_RESULTS:
            break
    return found


# ------------------------------------------------------------------ facade


def quote(symbol: str, provider: str, token: str = "") -> dict:
    """One validated quote. Raises ProviderError on an expected failure."""
    if provider == "finnhub":
        if not token:
            raise ProviderError("no Finnhub API key")
        return _finnhub_quote(symbol, token)
    return _yahoo_quote(symbol)


def search(query: str, provider: str, token: str = "") -> list[dict]:
    """Symbol lookup by name or ticker, best match first."""
    query = query.strip()[:64]
    if not query:
        return []
    if provider == "finnhub":
        if not token:
            raise ProviderError("no Finnhub API key")
        return _finnhub_search(query, token)
    return _yahoo_search(query)


def fx_rates(currencies: list[str], base: str, provider: str) -> tuple[dict, list[str]]:
    """Rates into `base` for the currencies given; returns (rates, failed).

    Only the Yahoo provider can price FX here, so the Finnhub path reports
    every foreign currency as failed instead of guessing a rate.
    """
    rates: dict[str, float] = {base: 1.0}
    failed: list[str] = []
    for currency in currencies:
        if not currency or currency == base:
            continue
        if provider != "yahoo":
            failed.append(currency)
            continue
        try:
            rate = _yahoo_rate(currency, base)
        except ProviderError:
            failed.append(currency)
            continue
        if rate is None or rate <= 0:
            failed.append(currency)
        else:
            rates[currency] = rate
    return rates, failed
