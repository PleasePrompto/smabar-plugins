"""Container engine access: command lines and parsers for Docker and Podman.

Pure text processing over what the CLIs print, so test_engine.py runs without
a bar. `ps --format '{{json .}}'` prints one JSON object per line on Docker
(strings everywhere: Names, Ports, Labels, Status). Podman renders the same
template over its own ListContainer struct (Id, Names as a list, Ports as
mappings, Labels as a map, StartedAt/ExitedAt as unix seconds, Status = the
health check) and answers `--format json` with one array; parse_ps accepts
all of these.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, replace

COMPOSE_PROJECT = "com.docker.compose.project"
ACTIONS = ("start", "stop", "restart")
# Docker's container-name grammar; it also keeps flags out of the argument list.
TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PS_FORMAT = "{{json .}}"
# `{{json .}}` would marshal a different struct on each engine; these
# placeholders are documented for both `docker stats` and `podman stats`.
STATS_FORMAT = "{{.ID}}\t{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
UP = re.compile(
    r"^Up (?P<age>.+?)(?: \((?P<health>healthy|unhealthy|health: starting)\))?(?: \(Paused\))?$"
)
ENDED = re.compile(r"^(?:Exited|Restarting) \((?P<code>\d+)\) (?P<age>.+) ago$")
HUMAN = re.compile(r"^(\d+) (second|minute|hour|day|week|month|year)s?$")
UNITS = {"second": "s", "minute": "min", "hour": "h", "day": "d", "week": "w", "month": "mo", "year": "y"}
PORT = re.compile(r"(?:\S*:)?(?P<host>\d+(?:-\d+)?)->(?P<target>\d+(?:-\d+)?)/(?P<proto>\w+)")
SIZE = re.compile(r"^([\d.]+)\s*([A-Za-z]+)$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console flash


class EngineError(Exception):
    """The engine could not answer; str() is the first line of its stderr."""


class EngineMissing(EngineError):
    """The configured binary does not exist."""


@dataclass(frozen=True)
class Container:
    id: str
    name: str
    image: str
    state: str
    since: str  # compact age of the state, e.g. "4 h"; "" when unknown
    exit_code: int | None
    health: str  # "healthy", "unhealthy", "starting" or ""
    ports: tuple[str, ...]
    project: str  # compose project label, "" when standalone
    cpu: float | None = None
    mem: float | None = None
    mem_text: str = ""

    @property
    def running(self) -> bool:
        return self.state == "running"


@dataclass(frozen=True)
class Stats:
    cpu: float
    mem: float
    mem_text: str


# --- commands ------------------------------------------------------------


def engine_name(binary: str) -> str:
    return "Podman" if "podman" in os.path.basename(binary).lower() else "Docker"


def ps_command(binary: str) -> list[str]:
    return [binary, "ps", "-a", "--format", PS_FORMAT]


def stats_command(binary: str) -> list[str]:
    return [binary, "stats", "--no-stream", "--format", STATS_FORMAT]


def version_commands(binary: str) -> tuple[list[str], list[str]]:
    """Docker answers the first; local Podman has no Server and answers the second."""
    return (
        [binary, "version", "--format", "{{.Server.Version}}"],
        [binary, "version", "--format", "{{.Client.Version}}"],
    )


def action_command(binary: str, action: str, target: str) -> list[str]:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    if not TARGET.match(target):
        raise ValueError("container must be a name or id: letters, digits, '_', '.' and '-'")
    return [binary, action, target]


def run(command: list[str], timeout: float = 10) -> str:
    """Stdout of one engine call; every failure becomes an EngineError."""
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW
        )
    except FileNotFoundError as error:
        raise EngineMissing(f"{command[0]} not found") from error
    except subprocess.TimeoutExpired as error:
        raise EngineError(f"{command[0]} {command[1]} timed out after {timeout:g} s") from error
    except OSError as error:
        raise EngineError(f"{command[0]}: {error.strerror or error}") from error
    if done.returncode != 0:
        raise EngineError(
            first_line(done.stderr) or f"{command[0]} {command[1]} failed with exit {done.returncode}"
        )
    return done.stdout


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


# --- ps ------------------------------------------------------------------


def parse_ps(output: str, now: float | None = None) -> list[Container]:
    """Containers from `ps -a`: JSON lines (Docker, Podman template) or one array (Podman json)."""
    text = output.strip()
    if not text:
        return []
    if text.startswith("["):
        records = json.loads(text)
    else:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    stamp = time.time() if now is None else now
    return [container(record, stamp) for record in records if isinstance(record, dict)]


def container(record: dict, now: float) -> Container:
    names = record.get("Names") or ""
    if isinstance(names, list):
        names = names[0] if names else ""
    labels = record.get("Labels") or {}
    if isinstance(labels, str):
        labels = dict(pair.split("=", 1) for pair in labels.split(",") if "=" in pair)
    state = str(record.get("State", "")).lower()
    if "StartedAt" in record:
        since, code, health = podman_status(record, state, now)
    else:
        since, code, health = docker_status(str(record.get("Status", "")))
    return Container(
        id=str(record.get("ID") or record.get("Id") or "")[:12],
        name=str(names).split(",")[0],
        image=str(record.get("Image", "")),
        state=state,
        since=since,
        exit_code=code,
        health=health,
        ports=format_ports(record.get("Ports") or ""),
        project=str(labels.get(COMPOSE_PROJECT, "")),
    )


def docker_status(status: str) -> tuple[str, int | None, str]:
    """(age, exit code, health) from Docker's Status column, e.g. "Up 4 hours (healthy)"."""
    if match := UP.match(status):
        return shorten(match["age"]), None, (match["health"] or "").removeprefix("health: ")
    if match := ENDED.match(status):
        return shorten(match["age"]), int(match["code"]), ""
    return "", None, ""


def podman_status(record: dict, state: str, now: float) -> tuple[str, int | None, str]:
    """Podman has no Status column; its Status field is the health check result."""
    health = str(record.get("Status") or "")
    if state in ("running", "paused"):
        return age(now - number(record.get("StartedAt"))), None, health
    if state in ("exited", "stopped"):
        return age(now - number(record.get("ExitedAt"))), int(number(record.get("ExitCode"))), ""
    return "", None, ""


def number(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def shorten(human: str) -> str:
    """Compact form of go-units' HumanDuration: "About an hour" → "1 h", "3 weeks" → "3 w"."""
    if human == "Less than a second":
        return "< 1 s"
    if human == "About a minute":
        return "1 min"
    if human == "About an hour":
        return "1 h"
    if match := HUMAN.match(human):
        return f"{match[1]} {UNITS[match[2]]}"
    return human


def age(seconds: float) -> str:
    """Compact age with go-units' thresholds, so Podman rows read like Docker rows."""
    whole = int(seconds)
    if whole < 1:
        return "< 1 s"
    if whole < 60:
        return f"{whole} s"
    minutes = whole // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    days = hours // 24
    if days < 14:
        return f"{days} d"
    if days < 60:
        return f"{days // 7} w"
    if days < 730:
        return f"{days // 30} mo"
    return f"{days // 365} y"


def format_ports(value: object) -> tuple[str, ...]:
    """Published ports as "host→container" chips. IPv4 and IPv6 bindings of one
    port collapse into a single chip; exposed-only ports have no host side and
    are left out."""
    if isinstance(value, list):
        chips = [
            chip(
                span(mapping.get("host_port"), mapping.get("range")),
                span(mapping.get("container_port"), mapping.get("range")),
                str(mapping.get("protocol") or "tcp"),
            )
            for mapping in value
            if isinstance(mapping, dict) and mapping.get("host_port")
        ]
    else:
        chips = [chip(m["host"], m["target"], m["proto"]) for m in PORT.finditer(str(value))]
    return tuple(dict.fromkeys(chips))


def span(start: object, count: object) -> str:
    first, size = int(number(start)), int(number(count))
    return str(first) if size <= 1 else f"{first}-{first + size - 1}"


def chip(host: str, target: str, protocol: str) -> str:
    return f"{host}→{target}" + ("" if protocol == "tcp" else f"/{protocol}")


# --- stats ---------------------------------------------------------------


def parse_stats(output: str) -> dict[str, Stats]:
    """Stats keyed by short id AND by name, from the tab-separated STATS_FORMAT lines."""
    found: dict[str, Stats] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        cid, name, cpu, usage, mem = parts
        try:
            stats = Stats(percent(cpu), percent(mem), tidy_size(usage.split("/")[0]))
        except ValueError:
            continue
        found[cid.strip()[:12]] = stats
        found[name.strip()] = stats
    return found


def percent(text: str) -> float:
    return float(text.strip().rstrip("%").replace(",", "."))


def tidy_size(text: str) -> str:
    """"91.79MiB" → "92 MiB", "1.234GiB" → "1.2 GiB"; anything else stays as printed."""
    match = SIZE.match(text.strip())
    if not match:
        return text.strip()
    value, unit = float(match[1]), match[2]
    figure = f"{value:.1f}".rstrip("0").rstrip(".") if value < 10 else f"{value:.0f}"
    return f"{figure} {unit}"


def with_stats(containers: list[Container], stats: dict[str, Stats]) -> list[Container]:
    merged = []
    for item in containers:
        found = stats.get(item.id) or stats.get(item.name)
        merged.append(
            replace(item, cpu=found.cpu, mem=found.mem, mem_text=found.mem_text) if found else item
        )
    return merged


# --- shaping -------------------------------------------------------------


def group(containers: list[Container]) -> list[tuple[str, list[Container]]]:
    """Sections by compose project, alphabetical; standalone containers last under ""."""
    buckets: dict[str, list[Container]] = {}
    for item in containers:
        buckets.setdefault(item.project, []).append(item)
    return [
        (project, sorted(buckets[project], key=lambda c: (not c.running, c.name.lower())))
        for project in sorted(buckets, key=lambda p: (p == "", p.lower()))
    ]


def counts(containers: list[Container]) -> tuple[int, int]:
    return sum(1 for item in containers if item.running), len(containers)
