"""Currency math on one ECB table. Pure stdlib, no bar needed.

A table maps currency codes to how much one unit of the base buys, e.g.
{"EUR": 1.0, "USD": 1.1551}. Cross rates fall out of the table for ANY pair,
so the base only decides which table is fetched.
"""

import re

PAIR_SPLIT = re.compile(r"[\s/:\-]+")
CODE = re.compile(r"[A-Z]{3}")


def cross_rate(rates: dict[str, float], src: str, dst: str) -> float:
    """How many dst one src buys; ValueError names a code the table lacks."""
    missing = [code for code in (src, dst) if code not in rates]
    if missing:
        raise ValueError(f"unknown currency {', '.join(missing)}; the ECB table has {', '.join(sorted(rates))}")
    return rates[dst] / rates[src]


def change_percent(rates: dict[str, float], previous: dict[str, float], src: str, dst: str) -> float | None:
    """Day-over-day move of the pair in percent; None when a table lacks a code."""
    if any(code not in rates or code not in previous for code in (src, dst)):
        return None
    today, before = cross_rate(rates, src, dst), cross_rate(previous, src, dst)
    return (today - before) / before * 100


def parse_pair(text: str) -> tuple[str, str] | None:
    """"EUR/USD" (also "eur-usd", "EUR USD") -> ("EUR", "USD"); None when malformed."""
    parts = [part for part in PAIR_SPLIT.split(text.strip().upper()) if part]
    if len(parts) != 2 or not all(CODE.fullmatch(part) for part in parts):
        return None
    return parts[0], parts[1]


def parse_rates(payload: object, base: str) -> tuple[str, dict[str, float]]:
    """(date, table) from a Frankfurter v2 rates response: a list of
    {date, base, quote, rate} rows. The base is pinned to 1.0."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("rates response is not a non-empty list of rows")
    table: dict[str, float] = {}
    date = ""
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("rates row is not an object")
        quote, rate, day = row.get("quote"), row.get("rate"), row.get("date")
        if (not isinstance(quote, str) or isinstance(rate, bool)
                or not isinstance(rate, int | float) or rate <= 0 or not isinstance(day, str)):
            raise ValueError(f"unusable rates row: {str(row)[:120]}")
        table[quote.upper()] = float(rate)
        date = max(date, day)
    table[base] = 1.0
    return date, table


def parse_currencies(payload: object) -> dict[str, str]:
    """{code: name} from a Frankfurter v2 currencies response; incomplete rows are skipped."""
    if not isinstance(payload, list):
        raise ValueError("currencies response is not a list")
    names = {}
    for row in payload:
        if isinstance(row, dict) and isinstance(row.get("iso_code"), str) and isinstance(row.get("name"), str):
            names[row["iso_code"].upper()] = row["name"]
    return names
