"""Target parsing, probes, the latency ring buffer and the up/down state machine.

Standard library only and no SDK import, so test_checks.py exercises every
rule here without a running bar by feeding fake samples to apply().
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

USER_AGENT = "smabar-uptime/1.0 (+https://smabar.com)"
# ping:host has no raw ICMP (that needs privileges on every platform), so it is
# a TCP connect to the ports almost every host answers on.
PING_PORTS = (443, 80)
MAX_WORKERS = 8
STATUSES = ("up", "down", "unknown")
FAILURE_CODES = ("timeout", "dns", "refused", "tls", "error")


class TargetError(ValueError):
    """A settings entry that cannot become a target; `code` is invalid or duplicate."""

    def __init__(self, code: str, entry: str) -> None:
        super().__init__(f"{code}: {entry}")
        self.code = code
        self.entry = entry


@dataclass(frozen=True)
class Target:
    name: str
    spec: str  # https://…, http://…, tcp://host:port or ping:host, as configured
    kind: str  # http | tcp | ping
    host: str
    port: int
    where: str  # what the row shows under the name: host, host:port


def parse_target(entry: str) -> Target:
    """'Name | target' or a bare target; the name defaults to the host."""
    name, separator, spec = entry.partition("|")
    if not separator:
        name, spec = "", entry
    name, spec = name.strip(), spec.strip()
    lowered = spec.lower()
    if lowered.startswith(("http://", "https://")):
        parts = urlsplit(spec)
        host = parts.hostname or ""
        if not host:
            raise TargetError("invalid", entry)
        return Target(name or host, spec, "http", host, 0, host)
    if lowered.startswith("tcp://"):
        parts = urlsplit(spec)
        try:
            host, port = parts.hostname or "", parts.port
        except ValueError as error:
            raise TargetError("invalid", entry) from error
        if not host or port is None:
            raise TargetError("invalid", entry)
        where = f"{host}:{port}"
        return Target(name or where, spec, "tcp", host, port, where)
    if lowered.startswith("ping:"):
        host = spec[5:].strip()
        if not host or any(char in host for char in " /:"):
            raise TargetError("invalid", entry)
        return Target(name or host, spec, "ping", host, 0, host)
    raise TargetError("invalid", entry)


def parse_targets(entries: list[object]) -> tuple[list[Target], list[TargetError]]:
    """Every usable target in order, plus one error per skipped entry.

    A repeated name or target is skipped: names address targets in the agent
    commands, and two entries for one target would sample it twice per round.
    """
    targets: list[Target] = []
    rejected: list[TargetError] = []
    seen_names: set[str] = set()
    seen_specs: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            rejected.append(TargetError("invalid", repr(entry)[:80]))
            continue
        try:
            target = parse_target(entry)
        except TargetError as error:
            rejected.append(error)
            continue
        if target.name.casefold() in seen_names or target.spec in seen_specs:
            rejected.append(TargetError("duplicate", entry))
            continue
        seen_names.add(target.name.casefold())
        seen_specs.add(target.spec)
        targets.append(target)
    return targets, rejected


# --- probes ------------------------------------------------------------------


def classify(error: object) -> str:
    """The short failure code a row shows; the view turns it into words."""
    if isinstance(error, socket.gaierror):
        return "dns"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionRefusedError):
        return "refused"
    if isinstance(error, ssl.SSLError):
        return "tls"
    return "error"


def probe_http(url: str, timeout: float) -> tuple[bool, str]:
    """GET with redirects; up when the final status is below 400.

    HEAD is deliberately not used: many hosts answer it with 405 or drop it.
    The body is never read, so a large page costs one round trip.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, str(response.status)
    except urllib.error.HTTPError as error:
        return False, str(error.code)
    except urllib.error.URLError as error:
        return False, classify(error.reason)
    except (OSError, http.client.HTTPException, ValueError) as error:
        return False, classify(error)


def probe_tcp(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "open"
    except OSError as error:
        return False, classify(error)


def probe_ping(host: str, timeout: float) -> tuple[bool, str]:
    ok, code = False, "error"
    for port in PING_PORTS:
        ok, code = probe_tcp(host, port, timeout)
        if ok:
            break
    return ok, code


def probe(target: Target, timeout: float) -> dict:
    """One sample: {t, ok, ms, code}; ms is the full round trip including failures."""
    started = time.monotonic()
    if target.kind == "http":
        ok, code = probe_http(target.spec, timeout)
    elif target.kind == "tcp":
        ok, code = probe_tcp(target.host, target.port, timeout)
    else:
        ok, code = probe_ping(target.host, timeout)
    return {
        "t": int(time.time()),
        "ok": ok,
        "ms": round((time.monotonic() - started) * 1000),
        "code": code,
    }


def probe_all(targets: list[Target], timeout: float) -> list[dict]:
    """Every target concurrently; the result order matches the input order."""
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(targets))) as pool:
        return list(pool.map(lambda target: probe(target, timeout), targets))


# --- ring buffer and state machine -----------------------------------------


def new_entry() -> dict:
    return {"status": "unknown", "since": None, "fails": 0, "history": []}


def valid_sample(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("t"), int)
        and isinstance(raw.get("ok"), bool)
        and isinstance(raw.get("ms"), int)
        and isinstance(raw.get("code"), str)
    )


def restore_entry(raw: object) -> dict:
    """A persisted entry with every field checked; anything else starts fresh."""
    entry = new_entry()
    if not isinstance(raw, dict):
        return entry
    if raw.get("status") in STATUSES:
        entry["status"] = raw["status"]
    since = raw.get("since")
    if isinstance(since, int) and not isinstance(since, bool):
        entry["since"] = since
    fails = raw.get("fails")
    if isinstance(fails, int) and not isinstance(fails, bool) and fails >= 0:
        entry["fails"] = fails
    history = raw.get("history")
    if isinstance(history, list):
        entry["history"] = [sample for sample in history if valid_sample(sample)]
    return entry


def apply(entry: dict, sample: dict, *, history_size: int, threshold: int) -> str | None:
    """Record a sample; returns "down" or "up" when the status flipped, else None.

    Down needs `threshold` consecutive failures, up the first success. `since`
    is the start of the failing streak for down and the recovering sample for up,
    so a "back up after 4 min" measures the whole outage.
    """
    entry["history"] = (entry["history"] + [sample])[-history_size:]
    if sample["ok"]:
        entry["fails"] = 0
        if entry["status"] == "up":
            return None
        was_down = entry["status"] == "down"
        entry["status"], entry["since"] = "up", sample["t"]
        return "up" if was_down else None
    entry["fails"] += 1
    if entry["status"] == "down" or entry["fails"] < threshold:
        return None
    streak_start = max(0, len(entry["history"]) - entry["fails"])
    entry["status"], entry["since"] = "down", entry["history"][streak_start]["t"]
    return "down"


def uptime_percent(history: list[dict]) -> float | None:
    if not history:
        return None
    return 100.0 * sum(1 for sample in history if sample["ok"]) / len(history)
