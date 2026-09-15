# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the unit math, the currency cross rates, the rendering and
the agent commands. Run: python3 test_convert.py — no bar needed."""

import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).parent
EN = json.loads((HERE / "locales/en.json").read_text(encoding="utf-8"))
DE = json.loads((HERE / "locales/de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)


def translate(key: str) -> str:
    assert key in EN, f"raw locale key {key}"
    return EN[key]


class _StubPlugin:
    """Enough of the SDK surface to import plugin.py without a running bar."""

    settings: dict = {}
    data_dir = Path(tempfile.mkdtemp())
    rendered: dict = {}
    warnings: list = []

    def every(self, *_args):
        return lambda fn: fn

    def on_action(self, *_args):
        return lambda fn: fn

    def on_ready(self, fn):
        return fn

    def on_settings_changed(self, fn):
        return fn

    def command(self, *_args, **_kwargs):
        return lambda fn: fn

    def log(self, level, message, **_fields):
        if level == "warn":
            self.warnings.append(message)

    def render(self, _tile, target, html, **_kwargs):
        self.rendered[target] = html

    def t(self, key):
        return translate(key)

    def run(self):
        pass


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


sys.modules["smabar_sdk"] = types.SimpleNamespace(Plugin=_StubPlugin, RpcError=_RpcError)
sys.path.insert(0, str(HERE))
import plugin  # noqa: E402
import rates as fx  # noqa: E402
import units  # noqa: E402


def close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


# --- units: round trips through every unit of every category -------------
for category in units.CATEGORY_ORDER:
    for src in units.units_of(category):
        for dst in units.units_of(category):
            assert close(units.convert(units.convert(123.456, src, dst), dst, src), 123.456), (src, dst)
assert close(units.convert(1, "km", "mi"), 0.621371192237334)
assert close(units.convert(1, "mi", "m"), 1609.344)
assert close(units.convert(1, "in", "cm"), 2.54)
assert close(units.convert(1, "lb", "g"), 453.59237)
assert close(units.convert(1, "ha", "m²"), 10000)
assert close(units.convert(1, "acre", "m²"), 4046.8564224)
assert close(units.convert(1, "gal", "l"), 3.785411784)
assert close(units.convert(100, "km/h", "m/s"), 100 / 3.6)
assert close(units.convert(1, "kn", "km/h"), 1.852)

# Temperature is affine, not proportional.
assert close(units.convert(0, "°C", "°F"), 32)
assert close(units.convert(100, "°C", "°F"), 212)
assert close(units.convert(-40, "°C", "°F"), -40)
assert close(units.convert(0, "K", "°C"), -273.15)
assert close(units.convert(300, "K", "°F"), 80.33)
assert close(units.convert(212, "°F", "K"), 373.15)

# Data: decimal against binary prefixes.
assert units.convert(1, "KB", "B") == 1000
assert units.convert(1, "KiB", "B") == 1024
assert close(units.convert(1, "GiB", "GB"), 1.073741824)
assert close(units.convert(1, "TB", "TiB"), 0.9094947017729282)
assert close(units.convert(1, "MiB", "KiB"), 1024)

for src, dst in (("km", "kg"), ("°C", "m"), ("B", "l")):
    try:
        units.convert(1, src, dst)
        raise AssertionError((src, dst))
    except ValueError as error:
        assert "cannot convert" in str(error), error
try:
    units.convert(1, "parsec", "km")
    raise AssertionError("unknown unit accepted")
except ValueError as error:
    assert "parsec" in str(error)

assert units.find_unit("KM") == "km"
assert units.find_unit(" m2 ") == "m²"
assert units.find_unit("c") == "°C"
assert units.find_unit("floz") == "fl oz"
assert units.find_unit("kib") == "KiB"
assert units.find_unit("kelvin") is None
assert units.find_unit("") is None
slugs = [units.slug(unit).lower() for unit in units.all_units()]
assert len(slugs) == len(set(slugs)) == 40, slugs
for unit in units.all_units():
    assert "convert.unit." + units.slug(unit) in EN, unit
for category in units.CATEGORY_ORDER:
    assert "convert.cat." + category in EN

# --- number formatting: fixed places, tiny values keep three significant digits
assert units.fmt(115.51, 2) == "115.51"
assert units.fmt(1555040, 2) == "1 555 040.00"
assert units.fmt(0.000123, 2) == "0.000123"
assert units.fmt(0.008, 2) == "0.008"
assert units.fmt(0.012, 2) == "0.01"
assert units.fmt(0, 2) == "0.00"
assert units.fmt(-0.0, 2) == "0.00"
assert units.fmt(1609.344, 4, trim=True) == "1 609.344"
assert units.fmt(1.155, 4) == "1.1550"
assert units.fmt(-40, 1) == "-40.0"
assert units.rate_line("km", "mi", 2) == "1 km = 0.6214 mi"
assert units.rate_line("mi", "m", 2) == "1 mi = 1 609.344 m"
assert units.rate_line("°C", "°F", 2) == "°F = °C × 1.8 + 32"
assert units.rate_line("K", "°C", 2) == "°C = K − 273.15"
assert units.rate_line("°F", "°C", 2) == "°C = °F × 0.5556 − 17.7778"

# --- currency cross rates from one fixed table ---------------------------
TABLE = {"EUR": 1.0, "USD": 1.1551, "GBP": 0.85598, "JPY": 178.52}
PREVIOUS = {"EUR": 1.0, "USD": 1.1592, "GBP": 0.85815}
assert close(fx.cross_rate(TABLE, "EUR", "USD"), 1.1551)
assert close(fx.cross_rate(TABLE, "USD", "GBP"), 0.85598 / 1.1551)
assert close(fx.cross_rate(TABLE, "JPY", "JPY"), 1)
assert close(fx.cross_rate(TABLE, "USD", "EUR") * fx.cross_rate(TABLE, "EUR", "USD"), 1)
try:
    fx.cross_rate(TABLE, "USD", "XYZ")
    raise AssertionError("unknown code accepted")
except ValueError as error:
    assert "XYZ" in str(error) and "EUR, GBP, JPY, USD" in str(error)
assert close(fx.change_percent(TABLE, PREVIOUS, "EUR", "USD"), (1.1551 - 1.1592) / 1.1592 * 100)
assert fx.change_percent(TABLE, PREVIOUS, "EUR", "JPY") is None
assert fx.parse_pair("EUR/USD") == ("EUR", "USD")
assert fx.parse_pair(" eur-usd ") == ("EUR", "USD")
assert fx.parse_pair("EUR USD") == ("EUR", "USD")
for malformed in ("EURUSD", "EUR/US", "", "EUR/USD/GBP"):
    assert fx.parse_pair(malformed) is None, malformed

# The v2 provider payload: rows with date/base/quote/rate, the base pinned to 1.
payload = [
    {"date": "2026-09-14", "base": "EUR", "quote": "USD", "rate": 1.1551},
    {"date": "2026-09-14", "base": "EUR", "quote": "gbp", "rate": 0.85598},
    {"date": "2026-09-14", "base": "EUR", "quote": "EUR", "rate": 1.0},
]
date, table = fx.parse_rates(payload, "EUR")
assert date == "2026-09-14" and table == {"USD": 1.1551, "GBP": 0.85598, "EUR": 1.0}, (date, table)
assert fx.parse_rates(payload[:2], "USD")[1]["USD"] == 1.0
for bad in ([], {"rates": {}}, [{"quote": "USD"}],
            [{"date": "2026-09-14", "quote": "USD", "rate": -1}],
            [{"date": "2026-09-14", "quote": "USD", "rate": True}]):
    try:
        fx.parse_rates(bad, "EUR")
        raise AssertionError(bad)
    except ValueError:
        pass
assert fx.parse_currencies([{"iso_code": "usd", "name": "US Dollar"}, {"iso_code": 5}, "x"]) == {"USD": "US Dollar"}

# --- rendering through the plugin, every state keeps the tile's shape ----
out = plugin.app.rendered
plugin.app.settings = {"favoritePair": "EUR/USD", "decimals": 2}
plugin.ready()
assert "EUR/USD" in out["tile"] and "–" in out["tile"] and "Rates unavailable" in out["tile"], out["tile"]
assert "sb-alert--warn" in out["flyout"] and "Rates unavailable" in out["flyout"]
assert out["flyout"].count('data-tab-panel="units" hidden') == 1
assert 'data-tab="currency"' in out["flyout"] and "sb-active" in out["flyout"]
assert "No conversion yet" in out["hover"]
assert out["tile"].count("<svg") == 1  # the glyph is part of the markup in every state

with plugin.lock:
    plugin.cache.update(date="2026-09-14", base="EUR", rates=dict(TABLE),
                        currencies={"EUR": "Euro", "USD": "United States Dollar"},
                        previous={"date": "2026-09-11", "rates": dict(PREVIOUS)})
plugin.render()
assert "1.1551" in out["tile"] and "arrow-down" in out["tile"] and "sb-crit" in out["tile"], out["tile"]
assert "-0.35 % since 2026-09-11" in out["tile"], out["tile"]
assert out["tile"].count("<svg") == 1 and out["tile"].index("<svg") < out["tile"].index('<span class="sb-muted">EUR/USD')
assert "115.51" in out["flyout"] and "1 EUR = 1.1551 USD · ECB 2026-09-14" in out["flyout"]
assert "USD · United States Dollar" in out["flyout"] and 'value="GBP"' in out["flyout"]
assert 'value="EUR" selected' in out["flyout"] and 'value="USD" selected' in out["flyout"]
assert "sb-faint" not in out["flyout"]  # the cached marker only after a failed download

plugin.on_action("convert-currency", {"cv-amount": "250,5", "cv-from": "USD", "cv-to": "JPY",
                                      "un-amount": "1", "un-from": "km", "un-to": "mi"})
assert plugin.state["currency"] == {"amount": 250.5, "from": "USD", "to": "JPY"}, plugin.state
expected = units.fmt(250.5 * 178.52 / 1.1551, 2)
assert out["hover"].count("250.5 USD = " + expected + " JPY") == 1, out["hover"]
assert expected in out["flyout"]
plugin.on_action("swap-currency", {"cv-amount": "250.5", "cv-from": "USD", "cv-to": "JPY"})
assert (plugin.state["currency"]["from"], plugin.state["currency"]["to"]) == ("JPY", "USD")
plugin.on_action("convert-currency", {"cv-amount": "abc", "cv-from": "USD", "cv-to": "EUR"})
assert plugin.state["currency"]["amount"] == 250.5 and 'aria-invalid="true"' in out["flyout"]
plugin.on_action("convert-currency", {"cv-amount": "1", "cv-from": "USD", "cv-to": "EUR"})
assert "aria-invalid" not in out["flyout"]
with plugin.lock:
    plugin.status["error"] = "URLError: offline"
plugin.render()
assert "· cached" in out["flyout"] and "1.1551" in out["tile"]
with plugin.lock:
    plugin.status["error"] = ""

plugin.on_action("tab", "units")
assert plugin.state["tab"] == "units" and 'data-tab-panel="currency" hidden' in out["flyout"]
plugin.on_action("category:temperature", {"un-amount": "37"})
assert plugin.state["units"] == {"category": "temperature", "amount": 37.0, "from": "°C", "to": "°F"}
assert "98.60" in out["flyout"] and "°F = °C × 1.8 + 32" in out["flyout"] and "is-selected" in out["flyout"]
plugin.on_action("convert-units", {"un-amount": "1", "un-from": "K", "un-to": "°C", "cv-amount": "1"})
assert plugin.state["last"] == "units" and "1 K = -272.15 °C" in out["hover"], out["hover"]
plugin.on_action("swap-units", {"un-amount": "1", "un-from": "K", "un-to": "°C"})
assert (plugin.state["units"]["from"], plugin.state["units"]["to"]) == ("°C", "K")
plugin.on_action("convert-units", {"un-amount": "1", "un-from": "km"})  # another category: ignored
assert (plugin.state["units"]["from"], plugin.state["units"]["to"]) == ("°C", "K")
plugin.app.warnings.clear()
plugin.on_action("tile", None)  # the shell sends this on a tile click: ignored, no warning
assert plugin.app.warnings == [] and plugin.state["units"]["from"] == "°C"

# State and cache survive a restart through the data directory.
plugin.save_state()
plugin.state.update(tab="currency")
plugin.state["units"].update({"category": "length", "amount": 1.0, "from": "km", "to": "mi"})
plugin.load_state()
assert plugin.state["tab"] == "units" and plugin.state["units"]["category"] == "temperature", plugin.state
plugin.save_cache()
plugin.cache.update(rates={}, previous=None)
plugin.load_cache()
assert plugin.cache["rates"] == TABLE and plugin.cache["previous"]["date"] == "2026-09-11"

# Bad settings fall back with one warning each; a pair off the table shows EUR/USD.
plugin.app.warnings.clear()
plugin.settings_changed({"baseCurrency": "euro", "favoritePair": "nope", "decimals": 99, "refreshHours": "x"})
assert plugin.cfg == {"base": "EUR", "pair": ("EUR", "USD"), "decimals": 2, "hours": 12.0}, plugin.cfg
assert len(plugin.app.warnings) == 4, plugin.app.warnings
plugin.app.warnings.clear()
plugin.settings_changed({"favoritePair": "EUR/XYZ"})
assert plugin.cfg["pair"] == ("EUR", "USD")
assert plugin.app.warnings == ["favoritePair is not on the ECB table; showing EUR/USD"], plugin.app.warnings
plugin.settings_changed({"favoritePair": "gbp/jpy", "decimals": 3})
assert plugin.cfg["pair"] == ("GBP", "JPY") and "GBP/JPY" in out["tile"]
assert units.fmt(178.52 / 0.85598, 4) in out["tile"], out["tile"]

# --- agent commands ------------------------------------------------------
result = plugin.cmd_convert({"amount": 100, "from": "eur", "to": "usd"})
assert result["kind"] == "currency" and close(result["value"], 115.51) and result["date"] == "2026-09-14", result
result = plugin.cmd_convert({"amount": 5, "from": "mi", "to": "km"})
assert result["kind"] == "unit" and close(result["value"], 8.04672) and close(result["rate"], 1.609344), result
assert result["category"] == "length" and result["line"] == "1 mi = 1.6093 km", result
result = plugin.cmd_convert({"amount": 20, "from": "C", "to": "F"})
assert close(result["value"], 68) and close(result["rate"], 1.8) and result["line"] == "°F = °C × 1.8 + 32", result
for bad in ({"amount": "1", "from": "km", "to": "mi"}, {"amount": 1, "from": "km", "to": "kg"},
            {"amount": 1, "from": "USD", "to": "km"}, {"amount": 1, "from": "", "to": "km"}):
    try:
        plugin.cmd_convert(bad)
        raise AssertionError(bad)
    except ValueError:
        pass
listing = plugin.cmd_rates({})
assert listing["base"] == "EUR" and listing["rates"]["USD"] == 1.1551 and listing["date"] == "2026-09-14"
with plugin.lock:
    plugin.cache["rates"] = {}
try:
    plugin.cmd_rates({})
    raise AssertionError("rates without a table")
except _RpcError:
    pass

print("ok")
