# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Self-check for the engine parsers and the markup. Run: python3 test_engine.py"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import engine  # noqa: E402
import views  # noqa: E402

HERE = Path(__file__).parent
EN = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
DE = json.loads((HERE / "locales" / "de.json").read_text(encoding="utf-8"))
assert set(EN) == set(DE), set(EN) ^ set(DE)


def t(key: str) -> str:
    """A translator that fails on a key the locale does not have."""
    return EN[key]


NOW = 1_800_000_000.0
COMPOSE = "com.docker.compose.project={project},com.docker.compose.service={service},com.docker.compose.version=5.5.0"


def docker_line(**fields: object) -> str:
    record = {
        "Command": '"docker-entrypoint.s…"', "CreatedAt": "2026-09-01 09:52:49 +0200 CEST",
        "Labels": "", "LocalVolumes": "0", "Mounts": "", "Networks": "bridge", "Platform": None,
        "Ports": "", "RunningFor": "2 weeks ago", "Size": "0B (virtual 199MB)", **fields,
    }
    return json.dumps(record)


# Six Docker lines, the shapes `docker ps -a --format '{{json .}}'` really prints.
DOCKER_PS = "\n".join([
    docker_line(ID="483ac650b1a7", Names="shop-web-1", Image="nginx:alpine", State="running",
                Status="Up 4 hours (healthy)", Ports="0.0.0.0:8080->80/tcp, [::]:8080->80/tcp",
                Labels=COMPOSE.format(project="shop", service="web")),
    docker_line(ID="ec4bdbb0800c", Names="shop-db-1", Image="postgres:17-alpine", State="exited",
                Status="Exited (0) 4 weeks ago", Labels=COMPOSE.format(project="shop", service="db")),
    docker_line(ID="905622bff74f", Names="worker", Image="python:3.12-slim", State="created", Status="Created"),
    docker_line(ID="1c0f9c3fdd0a", Names="mailpit", Image="axllent/mailpit", State="running",
                Status="Up 2 minutes (health: starting)",
                Ports="0.0.0.0:1025->1025/tcp, [::]:1025->1025/tcp, 0.0.0.0:8025->8025/tcp, [::]:8025->8025/tcp, 1110/tcp"),
    docker_line(ID="a8b814bd1021", Names="crashed", Image="busybox", State="exited",
                Status="Exited (137) About a minute ago"),
    docker_line(ID="0791a6726238", Names="cache", Image="redis:8.2-alpine", State="paused",
                Status="Up 5 minutes (Paused)", Ports="0.0.0.0:6379->6379/tcp, [::]:6379->6379/tcp"),
])

containers = engine.parse_ps(DOCKER_PS, now=NOW)
assert [c.id for c in containers] == ["483ac650b1a7", "ec4bdbb0800c", "905622bff74f", "1c0f9c3fdd0a", "a8b814bd1021", "0791a6726238"]
assert [c.name for c in containers] == ["shop-web-1", "shop-db-1", "worker", "mailpit", "crashed", "cache"]
assert [c.state for c in containers] == ["running", "exited", "created", "running", "exited", "paused"]
assert [c.since for c in containers] == ["4 h", "4 w", "", "2 min", "1 min", "5 min"], [c.since for c in containers]
assert [c.exit_code for c in containers] == [None, 0, None, None, 137, None]
assert [c.health for c in containers] == ["healthy", "", "", "starting", "", ""]
assert [c.project for c in containers] == ["shop", "shop", "", "", "", ""]
assert containers[0].ports == ("8080→80",), containers[0].ports
assert containers[3].ports == ("1025→1025", "8025→8025"), containers[3].ports  # 1110/tcp is exposed only
assert containers[1].ports == () and containers[0].image == "nginx:alpine"
assert containers[0].running and not containers[5].running
assert engine.parse_ps("   \n") == []

# Podman renders the same template over its ListContainer struct: Names is a
# list, Ports are mappings, Labels a map, Status the health check, times unix.
PODMAN = [
    {
        "Id": "9f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d",
        "Names": ["shop-web-1"], "Image": "docker.io/library/nginx:alpine", "State": "running",
        "Status": "healthy", "StartedAt": int(NOW - 4 * 3600), "ExitedAt": 0, "ExitCode": 0, "Exited": False,
        "Labels": {"com.docker.compose.project": "shop", "com.docker.compose.service": "web"},
        "Ports": [
            {"host_ip": "", "container_port": 80, "host_port": 8080, "range": 1, "protocol": "tcp"},
            {"host_ip": "", "container_port": 9000, "host_port": 9000, "range": 3, "protocol": "udp"},
        ],
    },
    {
        "Id": "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",
        "Names": ["batch"], "Image": "docker.io/library/busybox:latest", "State": "exited",
        "Status": "", "StartedAt": int(NOW - 3 * 86400), "ExitedAt": int(NOW - 2 * 86400), "ExitCode": 1,
        "Exited": True, "Labels": {}, "Ports": [],
    },
]
as_array = engine.parse_ps(json.dumps(PODMAN), now=NOW)
as_lines = engine.parse_ps("\n".join(json.dumps(record) for record in PODMAN), now=NOW)
assert as_array == as_lines
web, batch = as_array
assert web.id == "9f1c2d3e4a5b" and web.name == "shop-web-1" and web.project == "shop"
assert web.since == "4 h" and web.health == "healthy" and web.exit_code is None
assert web.ports == ("8080→80", "9000-9002→9000-9002/udp"), web.ports
assert batch.since == "2 d" and batch.exit_code == 1 and batch.ports == () and batch.project == ""

# Port strings of every shape Docker prints.
assert engine.format_ports("127.0.0.1:8000->8000/tcp") == ("8000→8000",)
assert engine.format_ports("0.0.0.0:53->53/udp, [::]:53->53/udp") == ("53→53/udp",)
assert engine.format_ports("0.0.0.0:8000-8005->8000-8005/tcp") == ("8000-8005→8000-8005",)
assert engine.format_ports("3306/tcp") == ()
assert engine.format_ports("") == ()

# go-units wording → compact, and the same thresholds from seconds.
assert engine.shorten("About an hour") == "1 h"
assert engine.shorten("Less than a second") == "< 1 s"
assert engine.shorten("1 second") == "1 s"
assert engine.shorten("3 months") == "3 mo"
assert engine.shorten("2 years") == "2 y"
assert engine.shorten("whatever") == "whatever"
assert [engine.age(s) for s in (0, 59, 3599, 47 * 3600, 48 * 3600, 13 * 86400, 14 * 86400, 60 * 86400, 800 * 86400)] == \
    ["< 1 s", "59 s", "59 min", "47 h", "2 d", "13 d", "2 w", "2 mo", "2 y"]

# Stats: the tab template prints strings on both engines; keyed by id and by name.
STATS = "\n".join([
    "483ac650b1a7\tshop-web-1\t0.10%\t91.79MiB / 60.6GiB\t0.15%",
    "1c0f9c3fdd0a\tmailpit\t12.5%\t1.234GiB / 60.6GiB\t2.04%",
    "9f1c2d3e4a5b\tpodman-style\t0,30%\t512kB / 8.1GB\t0.01%",
    "broken line without tabs",
    "0791a6726238\tcache\t--\t-- / --\t--",
])
stats = engine.parse_stats(STATS)
assert stats["483ac650b1a7"] == stats["shop-web-1"] == engine.Stats(0.1, 0.15, "92 MiB"), stats["shop-web-1"]
assert stats["mailpit"] == engine.Stats(12.5, 2.04, "1.2 GiB")
assert stats["podman-style"].cpu == 0.3 and stats["podman-style"].mem_text == "512 kB"
assert "cache" not in stats and len(stats) == 6
assert engine.tidy_size("0B") == "0 B" and engine.tidy_size("n/a") == "n/a"
merged = engine.with_stats(containers, stats)
assert merged[0].cpu == 0.1 and merged[0].mem_text == "92 MiB" and merged[3].cpu == 12.5
assert merged[1].cpu is None and merged[5].cpu is None

# Grouping: projects alphabetically, standalone last, running first inside a group.
grouped = engine.group(containers)
assert [project for project, _ in grouped] == ["shop", ""], grouped
assert [c.name for c in grouped[0][1]] == ["shop-web-1", "shop-db-1"]
assert [c.name for c in grouped[1][1]] == ["mailpit", "cache", "crashed", "worker"]
assert engine.counts(containers) == (2, 6)
assert engine.counts([]) == (0, 0)

# Commands: names and ids pass, flags and spaces do not.
assert engine.action_command("docker", "stop", "shop-web-1") == ["docker", "stop", "shop-web-1"]
assert engine.action_command("/usr/bin/podman", "start", "483ac650b1a7")[0] == "/usr/bin/podman"
for bad in ("--help", "-a", "a b", "", "x" * 129):
    try:
        engine.action_command("docker", "start", bad)
    except ValueError:
        pass
    else:
        raise AssertionError(bad)
try:
    engine.action_command("docker", "rm", "x")
except ValueError:
    pass
else:
    raise AssertionError("rm must be rejected")
assert engine.engine_name("podman") == "Podman"
assert engine.engine_name("/usr/local/bin/docker") == "Docker"
assert engine.engine_name(r"C:\Program Files\RedHat\Podman\podman.exe") == "Podman"
assert engine.ps_command("docker") == ["docker", "ps", "-a", "--format", "{{json .}}"]
assert engine.stats_command("docker")[1:3] == ["stats", "--no-stream"]
assert engine.first_line("\n  Cannot connect\nsecond") == "Cannot connect"


# Markup: every state keeps the tile's shape, no raw locale key, controls fit the state.
def snapshot(**overrides: object) -> dict:
    base = {"containers": merged, "phase": "ok", "error": "", "version": "29.1.3", "updated": "10:32", "busy": set()}
    return {**base, **overrides}


ok = views.tile(snapshot(), "Docker", t)
assert "2/6" in ok and "sb-accent" in ok and "docker." not in ok, ok
idle = views.tile(snapshot(containers=[containers[1]]), "Docker", t)
assert "0/1" in idle and "sb-muted" in idle
assert "No containers" in views.tile(snapshot(containers=[]), "Docker", t)
assert "Docker offline" in views.tile(snapshot(phase="offline"), "Docker", t) and "sb-crit" in views.tile(snapshot(phase="offline"), "Docker", t)
assert "Podman offline" in views.tile(snapshot(phase="offline"), "Podman", t)
assert "Not found" in views.tile(snapshot(phase="missing", containers=[]), "Docker", t)
assert "–" in views.tile(snapshot(phase="loading", containers=[]), "Docker", t)
for shape in (ok, idle, views.tile(snapshot(containers=[]), "Docker", t),
              views.tile(snapshot(phase="offline"), "Docker", t),
              views.tile(snapshot(phase="missing", containers=[]), "Docker", t),
              views.tile(snapshot(phase="loading", containers=[]), "Docker", t)):
    assert shape.startswith('<div class="sb-tile"><svg ') and 'width="1em"' in shape, shape  # icon first, every state

hover = views.hover(snapshot(), "Docker", t)
assert "2 running · shop-web-1, mailpit" in hover, hover
assert "Nothing running · 1 stopped" in views.hover(snapshot(containers=[containers[1]]), "Docker", t)

flyout = views.flyout(snapshot(), "Docker", "docker", 10, True, t)
assert "docker." not in flyout, flyout
assert "Engine 29.1.3 · 2 of 6 running" in flyout
assert flyout.count('class="sb-section"') == 2 and ">shop<" in flyout and ">Other<" in flyout
assert 'data-action="stop" data-value="483ac650b1a7"' in flyout and 'data-action="restart" data-value="483ac650b1a7"' in flyout
assert 'data-action="start" data-value="ec4bdbb0800c"' in flyout
assert 'data-action="start" data-value="483ac650b1a7"' not in flyout
assert 'aria-label="Stop shop-web-1" title="Stop shop-web-1"' in flyout
assert '<span class="sb-badge">8080→80</span>' in flyout
assert "CPU 0.1 % · RAM 92 MiB" in flyout and 'width: 12%' in flyout and "disabled" not in flyout
assert "Up 4 h" in flyout and "Exited 4 w ago" in flyout and "Exited (137) 1 min ago" in flyout and ">Paused<" in flyout
assert "Up 2 min · starting" in flyout and "sb-badge--danger" in flyout and "sb-badge--warn" in flyout
assert "Updated 10:32 · every 10 s" in flyout
assert "CPU" not in views.flyout(snapshot(), "Docker", "docker", 10, False, t)
busy = views.flyout(snapshot(busy={"483ac650b1a7"}), "Docker", "docker", 10, True, t)
assert 'data-action="stop" data-value="483ac650b1a7"' not in busy and "sb-spinner" in busy
offline = views.flyout(snapshot(phase="offline", error="Cannot connect to the Docker daemon"), "Docker", "docker", 10, True, t)
assert "sb-alert--danger" in offline and "Cannot connect" in offline and "Docker is not reachable" in offline
assert offline.count(" disabled>") == 9 and '<div class="sb-muted">' in offline, offline.count(" disabled>")
missing = views.flyout(snapshot(phase="missing", containers=[], error="docker not found"), "Docker", "docker", 10, True, t)
assert "docker not found" in missing and "sb-empty" not in missing
empty = views.flyout(snapshot(containers=[]), "Docker", "docker", 10, True, t)
assert "sb-empty" in empty and "No containers yet" in empty
loading = views.flyout(snapshot(phase="loading", containers=[], updated="", version=""), "Docker", "docker", 10, True, t)
assert "Reading containers…" in loading and "Updated" not in loading and "sb-meta" not in loading
single = views.flyout(snapshot(containers=[containers[2], containers[3]]), "Docker", "docker", 10, True, t)
assert 'class="sb-section"' not in single  # no compose project anywhere: no heading

popup = views.failure("Stop shop-web-1", "Error response from daemon: boom", t)
assert "Stop shop-web-1 failed" in popup and "boom" in popup

print("ok")
