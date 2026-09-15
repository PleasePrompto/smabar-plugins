"""Unit tables and conversion math. Pure stdlib, no bar needed.

Every linear category maps a unit symbol to its factor towards the category's
base unit (metre, kilogram, square metre, litre, metre per second, byte).
Temperature scales are offset, not proportional, so they convert through
kelvin with their own two functions.
"""

import math

LINEAR: dict[str, dict[str, float]] = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
               "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344},
    "mass": {"g": 0.001, "kg": 1.0, "t": 1000.0, "oz": 0.028349523125, "lb": 0.45359237},
    "area": {"m²": 1.0, "km²": 1_000_000.0, "ft²": 0.09290304, "acre": 4046.8564224, "ha": 10_000.0},
    # US customary: fluid ounce, gallon and cup.
    "volume": {"ml": 0.001, "l": 1.0, "m³": 1000.0, "fl oz": 0.0295735295625,
               "gal": 3.785411784, "cup": 0.2365882365},
    "speed": {"km/h": 1 / 3.6, "m/s": 1.0, "mph": 0.44704, "kn": 1852 / 3600},
    "data": {"B": 1.0, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
             "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3, "TiB": 1024.0**4},
}
TEMPERATURE = ("°C", "°F", "K")
CATEGORY_ORDER = ("length", "mass", "temperature", "area", "volume", "speed", "data")
# ASCII spellings: locale keys and what an agent may type instead of the symbol.
ASCII = {"°C": "c", "°F": "f", "m²": "m2", "km²": "km2", "ft²": "ft2",
         "m³": "m3", "fl oz": "floz", "km/h": "kmh", "m/s": "ms"}


def units_of(category: str) -> tuple[str, ...]:
    return TEMPERATURE if category == "temperature" else tuple(LINEAR[category])


def category_of(unit: str) -> str | None:
    if unit in TEMPERATURE:
        return "temperature"
    return next((name for name, table in LINEAR.items() if unit in table), None)


def slug(unit: str) -> str:
    return ASCII.get(unit, unit)


def find_unit(text: str) -> str | None:
    """The unit symbol for a symbol or ASCII spelling, case-insensitively."""
    wanted = text.strip().lower()
    for category in CATEGORY_ORDER:
        for unit in units_of(category):
            if wanted in (unit.lower(), slug(unit).lower()):
                return unit
    return None


def _to_kelvin(value: float, unit: str) -> float:
    if unit == "°C":
        return value + 273.15
    if unit == "°F":
        return (value - 32) * 5 / 9 + 273.15
    return value


def _from_kelvin(value: float, unit: str) -> float:
    if unit == "°C":
        return value - 273.15
    if unit == "°F":
        return (value - 273.15) * 9 / 5 + 32
    return value


def convert(amount: float, src: str, dst: str) -> float:
    """amount in src expressed in dst; ValueError names an unknown or mismatched unit."""
    category = category_of(src)
    if category is None or category_of(dst) is None:
        unknown = src if category is None else dst
        raise ValueError(f"unknown unit {unknown!r}; known: {', '.join(all_units())}")
    if category != category_of(dst):
        raise ValueError(f"cannot convert {src} ({category}) to {dst} ({category_of(dst)})")
    if category == "temperature":
        return _from_kelvin(_to_kelvin(amount, src), dst)
    return amount * LINEAR[category][src] / LINEAR[category][dst]


def all_units() -> list[str]:
    return [unit for category in CATEGORY_ORDER for unit in units_of(category)]


def fmt(value: float, decimals: int, *, trim: bool = False) -> str:
    """Fixed decimals with a narrow no-break space between thousands, so the
    decimal point stays unambiguous in every locale. A non-zero value that the
    fixed places would show as 0 keeps three significant digits instead."""
    if value == 0:
        value = 0.0  # drops the sign of -0.0
    places = decimals
    tiny = value != 0 and abs(value) < 10**-decimals
    if tiny:
        places = min(12, 2 - math.floor(math.log10(abs(value))))
    text = f"{value:,.{places}f}".replace(",", " ")
    if (trim or tiny) and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def rate_line(src: str, dst: str, decimals: int) -> str:
    """The factor as text ("1 km = 0.6214 mi"); temperature gets its formula."""
    places = max(decimals, 4)
    if category_of(src) == "temperature":
        offset = convert(0, src, dst)
        slope = convert(1, src, dst) - offset
        factor = "" if abs(slope - 1) < 1e-9 else f" × {fmt(slope, places, trim=True)}"
        shift = "" if abs(offset) < 1e-9 else f" {'+' if offset > 0 else '−'} {fmt(abs(offset), places, trim=True)}"
        return f"{dst} = {src}{factor}{shift}"
    return f"1 {src} = {fmt(convert(1, src, dst), places, trim=True)} {dst}"
