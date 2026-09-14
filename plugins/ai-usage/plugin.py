# /// script
# requires-python = ">=3.12"
# dependencies = ["pywinpty>=3.0; sys_platform == 'win32'"]
# ///
"""Claude and Codex quota usage in one tile, read from the local CLIs — no API keys.

Only installed agents are shown: Claude when its CLI or ~/.claude.json exists,
Codex when its CLI or ~/.codex exists. Claude comes first, Codex beneath it.

Claude: runs `claude /usage` in a pseudo terminal and scrapes the rendered TUI
(there is no headless quota command). Linux and macOS use the stdlib pty,
Windows a ConPTY through pywinpty — the dialog driving is the same on both.
The probe runs in an empty folder inside app.data_dir so the CLI's folder-trust
prompt applies to that throwaway folder instead of the user's home. Takes ~3s,
so it polls slowly and off the handler thread.

Codex: reads the newest `~/.codex/sessions/**/rollout-*.jsonl` and takes the
last `rate_limits` block the server sent (used_percent, window_minutes,
resets_at, plan_type). Zero processes — but the numbers are only as fresh as
the last Codex activity, which is why the flyout shows that timestamp.
"""

import glob
import html
import json
import os
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from smabar_sdk import Plugin

if sys.platform == "win32":
    from winpty import PtyProcess  # ConPTY; the header installs it on Windows only
else:
    import fcntl
    import pty
    import termios

app = Plugin()

TILE = "usage"
TICK_SECONDS = 5.0
CODEX_INTERVAL = 60.0
DEFAULT_CLAUDE_MINUTES = 15
PROBE_TIMEOUT = 60.0
PROBE_SETTLE = 1.5  # keep reading this long after the first parsable frame
ROWS, COLS = 200, 120  # tall, so the whole usage screen fits without scrolling
CLAUDE_CONFIG = Path.home() / ".claude.json"
CODEX_HOME = Path.home() / ".codex"
CODEX_SESSIONS = CODEX_HOME / "sessions"
CODEX_CANDIDATES = 6
TAIL_BYTES = 262_144  # rate_limits arrive with every token_count event

CLAUDE_FALLBACK_BINS = (
    "~/.local/bin/claude",  # native installer on Linux and macOS
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
    "~/.local/bin/claude.exe",  # native installer on Windows
    "~/AppData/Roaming/npm/claude.cmd",  # npm -g on Windows
)

# The TUI positions text with cursor jumps; stripping those glues words together,
# so prompt detection matches against a whitespace-free copy of the screen.
ANSI = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b\[[0-9;:?<>=]*[a-zA-Z]"  # CSI
    r"|\x1b[()][0-9A-Za-z]|\x1b[=>]"  # charset / keypad
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f]"  # stray control bytes
)
# Only startup prompts — never a generic "Esc to cancel", which the usage screen
# itself shows: an Enter there switches its tabs and scrolls the quotas away.
PROMPTS = ("Itrustthisfolder", "Readytocodehere", "PressEntertocontinue")
DIALOG_OPEN = "Esctocancel"  # footer of the /usage dialog, on every one of its tabs
# Markers of the Usage tab itself — "Current session" only appears once the quota
# request comes back, so without these the navigation would walk on past it.
ON_USAGE_TAB = ("Currentsession", "Loadingusagedata", "Totalcost:")
TAB_STEPS = 4  # tabs to the left of Usage: Settings, Status, Config (plus slack)
ENTER = b"\r"
LEFT_ARROW = b"\x1b[D"
RIGHT_ARROW = b"\x1b[C"
DOWN_ARROW = b"\x1b[B"
CURSOR = "❯"  # the trust dialog's selection marker
DECLINE_SELECTED = CURSOR + "No,exit"  # newer CLIs preselect "No, exit" in the trust dialog
# Every gap is \s* : whether two words keep their space depends on how the TUI
# positioned them, so "Current session" and "Currentsession" both have to match.
# "Rese?t?s": the TUI occasionally drops a character while redrawing ("Reses 10am").
RE_SESSION = re.compile(
    r"Current\s*session[^%]*?(\d{1,3})\s*%\s*used\s*(?:Rese?t?s\s*([^(\n]{0,24}))?"
)
RE_WEEK = re.compile(
    r"Current\s*week\s*\(([^)]{1,24})\)[^%]*?(\d{1,3})\s*%\s*used\s*(?:Rese?t?s\s*([^(\n]{0,24}))?"
)
RE_PLAN = re.compile(r"Claude (Max|Pro|Team|Enterprise)")
RE_NO_SUB = re.compile(r"only available for subscription", re.I)

# Brand marks as 24x24 path data, drawn in currentColor so they follow the theme.
LOGO_PATHS = {
    "claude": (
        "M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121"
        "L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098"
        "-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061"
        ".893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032"
        "-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03"
        ".456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685"
        "-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431"
        "h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28"
        " 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036"
        "h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068"
        " 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649"
        " 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254"
        "-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018"
        "-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086"
        "-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z"
    ),
    "codex": (
        "M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662"
        " 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 00-.856 0l-5.97 3.473zm10.609 8.8V12.06"
        "c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 01.476 0l4.543 2.617c1.309.76 2.189 2.378"
        " 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163zM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899"
        "c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898z"
        "M12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128zm1.796 7.23c-1 0-1.927-.332-2.712-.927"
        "l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974"
        " 4.472-4.614 4.472zm-5.637-5.303l-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 014.21"
        " 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 01-.476 0zm-.262 3.9c-2.688 0"
        "-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19"
        "-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523zm5.899 2.83a5.947 5.947 0 005.827-4.756"
        "C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759"
        "-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0010.205 0a5.947 5.947 0 00-5.827 4.757"
        "C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946"
        " 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 004.162 1.713z"
    ),
}

# Display order: Claude first, Codex beneath it. accent re-brands each card (a documented token).
PROVIDERS = {
    "claude": {"title": "Claude", "accent": "#d97757"},
    "codex": {"title": "Codex", "accent": "#10a37f"},
}
NONE_INSTALLED = "No Claude Code or Codex CLI found"

# limits: [{"label", "pct", "reset"}] — a newer successful read wins, errors never clear it.
state: dict = {
    "claude": {"limits": [], "plan": "", "error": "", "at": ""},
    "codex": {"limits": [], "plan": "", "error": "", "at": ""},
    "installed": [],  # provider ids found on this machine, in PROVIDERS order
    "claude_polled": 0.0,
    "codex_polled": 0.0,
    "probing": False,
    "dirty": True,
}


def esc(text: object) -> str:
    return html.escape(str(text))


def clock() -> str:
    return datetime.now().strftime("%H:%M")


# --- Detection ------------------------------------------------------------


def claude_binary() -> str | None:
    """Configured binary, PATH lookup, then the usual install locations.

    The bar is a desktop process, so its PATH often misses ~/.local/bin.
    """
    name = str(app.settings.get("claudeBinary") or "claude").strip() or "claude"
    found = shutil.which(name)
    if found:
        return found
    if os.sep in name or "/" in name:
        expanded = os.path.expanduser(name)
        return expanded if os.access(expanded, os.X_OK) else None
    for candidate in CLAUDE_FALLBACK_BINS:
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return None


def detect() -> list[str]:
    """Installed agents. A CLI's config folder counts too, so a PATH problem shows
    up as an error inside the plugin instead of silently hiding the agent."""
    found = []
    if claude_binary() or CLAUDE_CONFIG.is_file():
        found.append("claude")
    if shutil.which("codex") or CODEX_HOME.is_dir():
        found.append("codex")
    return found


# --- Claude ---------------------------------------------------------------


class UnixTerminal:
    """`claude` on a stdlib pty (Linux, macOS).

    `timeout` guarantees the CLI dies even if this plugin is killed mid-probe:
    the child runs in its own session, so it would otherwise outlive us.
    --foreground keeps it in the pty's foreground group so it still reads keys.
    """

    def __init__(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        guard = shutil.which("timeout")
        if guard:
            argv = [guard, "--foreground", "-k", "5", str(int(PROBE_TIMEOUT)), *argv]
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=cwd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)

    def read(self, timeout: float) -> bytes | None:
        """Output that arrived within `timeout`; b"" when nothing did, None once the CLI is gone."""
        ready, _, _ = select.select([self.master], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(self.master, 65536) or None
        except OSError:
            return None

    def write(self, keys: bytes) -> None:
        os.write(self.master, keys)

    def close(self) -> None:
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self.proc.wait(timeout=5)
        os.close(self.master)


class WindowsTerminal:
    """`claude` on a ConPTY through pywinpty.

    pywinpty pumps the console output into a local socket (proc.fileobj), so
    the same select()-based waiting works here. Ceiling: no external kill guard —
    if smabar kills this plugin mid-probe, the CLI may linger until its own exit.
    """

    def __init__(self, argv: list[str], cwd: str, env: dict[str, str]) -> None:
        if argv[0].lower().endswith((".cmd", ".bat")):  # the npm shim needs the shell
            argv = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *argv]
        self.proc = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(ROWS, COLS))

    def read(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self.proc.fileobj], [], [], timeout)
        if not ready:
            return b""
        try:
            return self.proc.read(65536).encode("utf-8")
        except EOFError:
            return None

    def write(self, keys: bytes) -> None:
        self.proc.write(keys.decode("ascii"))

    def close(self) -> None:
        try:
            self.proc.close(force=True)
        except OSError as error:
            app.log("warn", "claude probe process did not terminate", error=str(error))


def run_usage(binary: str) -> str:
    """Drives `claude /usage` in a pseudo terminal and returns the de-ANSI'd screen text."""
    probe_dir = app.data_dir / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    # A setup-token in CLAUDE_CODE_OAUTH_TOKEN only carries the inference scope
    # and cannot read quotas — drop it so the CLI uses the stored login instead.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    env["TERM"] = "xterm-256color"
    terminal_class = WindowsTerminal if sys.platform == "win32" else UnixTerminal
    term = terminal_class([binary, "/usage"], str(probe_dir), env)
    buffer = b""

    def screen() -> tuple[str, str]:
        """Full de-ANSI'd text, plus a whitespace-free copy of it.

        Cursor-positioned text loses its spaces when the escapes go, so prompt
        and tab markers are matched against the whitespace-free form.
        """
        text = ANSI.sub("", buffer.decode("utf-8", "replace"))
        return text, re.sub(r"\s+", "", text)

    def pump(seconds: float, until=None) -> tuple[str, str]:
        nonlocal buffer
        end = time.monotonic() + seconds
        state_now = screen()
        while time.monotonic() < end:
            chunk = term.read(0.25)
            if chunk is None:
                break
            if chunk:
                buffer += chunk
                state_now = screen()
            if until and until(*state_now):
                break
        return state_now

    def on_usage(flat: str) -> bool:
        """Whether the quota tab was reached — true once its content was seen."""
        return any(marker in flat for marker in ON_USAGE_TAB)

    # A prompt or the dialog footer is a property of the CURRENT frame, and the
    # buffer holds every frame — so those markers only ever look at its tail.
    def current(flat: str) -> str:
        return flat[-1500:]

    try:
        text, flat = pump(
            20.0,
            lambda _t, f: DIALOG_OPEN in current(f)
            or any(p in current(f) for p in PROMPTS),
        )
        if any(prompt in current(flat) for prompt in PROMPTS):
            text, flat = pump(1.0)  # a key sent while the dialog still mounts is reset by its re-render
            for _ in range(3):  # newer CLIs preselect "No, exit": move the cursor onto "Yes" first
                if not flat[flat.rfind(CURSOR) :].startswith(DECLINE_SELECTED):
                    break
                term.write(DOWN_ARROW)
                text, flat = pump(0.6)
            term.write(ENTER)  # confirm the folder-trust prompt, once
            text, flat = pump(20.0, lambda _t, f: DIALOG_OPEN in current(f))
        if not on_usage(flat):
            # The dialog reopens on whichever tab was used last. Walk to the
            # leftmost tab, then step right until the quota tab shows up — that
            # survives a different starting tab and a reordered tab bar.
            for _ in range(TAB_STEPS):
                term.write(LEFT_ARROW)
                pump(0.35)
            for _ in range(TAB_STEPS + 1):
                text, flat = pump(1.5, lambda _t, f: on_usage(f))
                if on_usage(flat):
                    break
                term.write(RIGHT_ARROW)
        text, _ = pump(25.0, lambda t, _f: RE_SESSION.search(t) is not None)
        if RE_SESSION.search(text):
            text, _ = pump(PROBE_SETTLE)  # let the remaining quota rows arrive
    finally:
        term.close()
    return text


def tidy(text: str) -> str:
    """Re-space a label the TUI may have rendered glued together ("Aug26,3pm")."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    collapsed = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", collapsed)
    return re.sub(r",(?=\S)", ", ", collapsed)


def claude_plan() -> str:
    """Plan badge from ~/.claude.json, e.g. "default_claude_max_20x" -> "Max 20×".

    The /usage screen itself only names the plan in the welcome banner, which a
    fast probe never renders — the stored account profile always has it.
    """
    try:
        config = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        app.log("debug", "claude account profile unreadable", error=str(error))
        return ""
    account = config.get("oauthAccount")
    if not isinstance(account, dict):
        return ""
    source = str(account.get("organizationRateLimitTier") or account.get("organizationType") or "")
    match = re.search(r"(max|pro|team|enterprise)(?:_(\d+)x)?", source)
    if not match:
        return ""
    name = match.group(1).capitalize()
    return f"{name} {match.group(2)}×" if match.group(2) else name


def parse_claude(text: str) -> tuple[list[dict], str]:
    """Last rendered frame wins: findall keeps every frame, we take the newest."""
    limits: dict[str, dict] = {}
    sessions = RE_SESSION.findall(text)
    if sessions:
        pct, reset = sessions[-1]
        limits["session"] = {"label": "Session", "pct": int(pct), "reset": tidy(reset)}
    for name, pct, reset in RE_WEEK.findall(text):
        key = re.sub(r"\s+", "", name)
        label = "Week" if key == "allmodels" else f"Week · {tidy(name)}"
        limits[f"week:{key}"] = {"label": label, "pct": int(pct), "reset": tidy(reset)}
    plans = RE_PLAN.findall(text)
    return list(limits.values()), (plans[-1] if plans else "")


def probe_claude() -> None:
    data = state["claude"]
    binary = claude_binary()
    if not binary:
        data["error"] = "Claude CLI not found — set claudeBinary in the plugin settings."
        return
    try:
        text = run_usage(binary)
    except (OSError, EOFError, subprocess.SubprocessError) as error:
        data["error"] = f"Probe failed: {error}"
        app.log("warn", "claude probe failed", error=str(error), binary=binary)
        return
    limits, plan = parse_claude(text)
    if not limits:
        data["error"] = (
            "Account has no subscription quota (pay-as-you-go)."
            if RE_NO_SUB.search(text)
            else "Could not read the usage screen."
        )
        app.log("warn", "claude usage not parsable", chars=len(text), tail=text[-300:])
        return
    plan = claude_plan() or plan
    data.update({"limits": limits, "plan": plan, "error": "", "at": clock()})
    app.log("info", "claude usage updated", plan=plan, limits=len(limits))


def probe_claude_async() -> None:
    def worker() -> None:
        try:
            probe_claude()
        finally:
            state["probing"] = False
            state["dirty"] = True

    state["probing"] = True
    state["claude_polled"] = time.monotonic()
    threading.Thread(target=worker, name="claude-usage-probe", daemon=True).start()


# --- Codex ----------------------------------------------------------------


def window_label(minutes: object) -> str:
    if not isinstance(minutes, int | float) or minutes <= 0:
        return "Usage"
    total = int(minutes)
    if total % 1440 == 0:
        return f"{total // 1440}-day"
    if total % 60 == 0:
        return f"{total // 60}-hour"
    return f"{total}-minute"


def reset_label(resets_at: object) -> str:
    if not isinstance(resets_at, int | float) or resets_at <= 0:
        return ""
    when = datetime.fromtimestamp(float(resets_at))
    same_day = when.date() == datetime.now().date()
    return when.strftime("%H:%M" if same_day else "%b %d, %H:%M")


def tail_rate_limits(path: str) -> tuple[str, dict] | None:
    """Newest rate_limits block in the tail of one rollout file."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))
            lines = handle.read().split(b"\n")
    except OSError as error:
        app.log("debug", "codex rollout unreadable", path=path, error=str(error))
        return None
    for raw in reversed(lines):
        if b'"rate_limits"' not in raw:
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue  # truncated first line of the tail window
        limits = (event.get("payload") or {}).get("rate_limits")
        if isinstance(limits, dict) and (limits.get("primary") or limits.get("secondary")):
            return str(event.get("timestamp") or ""), limits
    return None


def read_codex() -> None:
    """Rollout paths sort chronologically by name, so no stat() over 1000+ files."""
    data = state["codex"]
    files = sorted(
        glob.glob(str(CODEX_SESSIONS / "*" / "*" / "*" / "rollout-*.jsonl")), reverse=True
    )[:CODEX_CANDIDATES]
    if not files:
        data["error"] = "No Codex sessions yet — run Codex once."
        return
    for path in files:
        found = tail_rate_limits(path)
        if not found:
            continue
        stamp, limits = found
        rows = []
        for key in ("primary", "secondary"):
            window = limits.get(key)
            if not isinstance(window, dict):
                continue
            pct = window.get("used_percent")
            if not isinstance(pct, int | float):
                continue
            rows.append(
                {
                    "label": window_label(window.get("window_minutes")),
                    "pct": max(0, min(100, round(pct))),
                    "reset": reset_label(window.get("resets_at")),
                }
            )
        if not rows:
            continue
        data.update(
            {
                "limits": rows,
                "plan": str(limits.get("plan_type") or ""),
                "error": "",
                # ISO timestamp of the event, e.g. 2026-08-22T14:57:34.684Z (UTC)
                "at": stamp[11:16] if len(stamp) >= 16 else clock(),
            }
        )
        return
    data["error"] = "No rate limits in the recent sessions — run Codex once."


# --- Rendering ------------------------------------------------------------


def status_class(pct: int) -> str:
    """Kit status class for a quota percentage; the number itself is always shown too."""
    if pct >= 85:
        return "sb-crit"
    if pct >= 60:
        return "sb-warn"
    return ""


def worst(limits: list[dict]) -> dict | None:
    return max(limits, key=lambda item: item["pct"]) if limits else None


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def logo(provider: str, size: int) -> str:
    """The agent's brand mark as inline SVG in currentColor; named for screen readers."""
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="currentColor" fill-rule="evenodd"'
        f' role="img" aria-label="{PROVIDERS[provider]["title"]}"><path d="{LOGO_PATHS[provider]}"/></svg>'
    )


def tile_column(provider: str) -> str:
    """One column of the tile: the brand mark and the highest quota, "–" before data."""
    peak = worst(state[provider]["limits"])
    value = f'<span class="{status_class(peak["pct"])}">{peak["pct"]}%</span>' if peak else "<span>–</span>"
    return f'<span class="sb-inline">{logo(provider, 15)}{value}</span>'


def render_tile() -> None:
    """statSplit cover: one column per installed agent; a lone column has no divider."""
    installed = state["installed"]
    if not installed:
        title = NONE_INSTALLED
        columns = f'<span class="sb-inline">{icon("gauge")}<span>–</span></span>'
    else:
        tips = []
        for provider in installed:
            peak = worst(state[provider]["limits"])
            name = PROVIDERS[provider]["title"]
            tips.append(f"{name} {peak['label']} {peak['pct']}% used" if peak else f"{name} no data")
        title = " · ".join(tips)
        columns = "".join(tile_column(provider) for provider in installed)
    app.render(
        TILE,
        "tile",
        f'<div class="sb-tile" title="{esc(title)}"><span class="sb-tile-split">{columns}</span></div>',
    )


def hover_block(provider: str) -> str:
    data = state[provider]
    peak = worst(data["limits"])
    value = (
        f'<span class="sb-push {status_class(peak["pct"])}">{peak["pct"]}%</span>'
        if peak
        else '<span class="sb-push sb-muted">–</span>'
    )
    detail = f'<span class="sb-muted">{esc(peak["label"])}</span>' if peak else ""
    return f'<div class="sb-row">{logo(provider, 16)}<span>{PROVIDERS[provider]["title"]}</span>{detail}{value}</div>'


def render_hover() -> None:
    installed = state["installed"]
    body = (
        f'<div class="sb-list">{"".join(hover_block(p) for p in installed)}</div>'
        if installed
        else f'<p class="sb-muted">{NONE_INSTALLED}</p>'
    )
    app.render(TILE, "hover", body)


def meter(provider: str, limit: dict) -> str:
    """One quota: label, reset time and percentage on a line, the progress track beneath."""
    pct = limit["pct"]
    reset = f'<span class="sb-muted">resets {esc(limit["reset"])}</span>' if limit["reset"] else ""
    return (
        f'<div class="sb-inline"><span>{esc(limit["label"])}</span>{reset}'
        f'<span class="sb-push {status_class(pct)}">{pct}%</span></div>'
        f'<div class="sb-progress"><span style="width: {pct}%"'
        f' data-sb-key="{provider}:{esc(limit["label"])}"></span></div>'
    )


def card(provider: str) -> str:
    """One agent as a brand-accented card: mark, name and plan up top, a meter per quota below."""
    data = state[provider]
    meta = PROVIDERS[provider]
    badge = f'<span class="sb-badge sb-push">{esc(data["plan"])}</span>' if data["plan"] else ""
    head = (
        f'<div class="sb-card__header"><span class="sb-card__icon">{logo(provider, 20)}</span>'
        f'<h3 class="sb-card__title">{meta["title"]}</h3>{badge}</div>'
    )
    if not data["limits"]:
        body = f'<p class="sb-muted">{esc(data["error"] or "Waiting for the first read…")}</p>'
    else:
        body = "".join(meter(provider, limit) for limit in data["limits"])
        if data["error"]:
            body += (
                f'<div class="sb-alert sb-alert--warn"><span class="sb-alert__icon">{icon("triangle-alert")}</span>'
                f'<div class="sb-alert__text">{esc(data["error"])}</div></div>'
            )
    stamp = (
        f"Updated {data['at'] or '–'} · claude /usage"
        if provider == "claude"
        else f"As of {data['at'] or '–'} UTC · last Codex activity"
    )
    return (
        f'<article class="sb-card sb-card--accent" style="--sb-accent: {meta["accent"]}">{head}'
        f'<div class="sb-card__body">{body}<p class="sb-meta">{esc(stamp)}</p></div></article>'
    )


def render_flyout() -> None:
    installed = state["installed"]
    probing = state["probing"]
    button = (
        '<button type="button" class="sb-btn sb-btn-ghost sb-btn-icon" data-action="refresh"'
        f' title="Refresh now" aria-label="Refresh now"{" disabled" if probing else ""}>'
        f'{icon("loader-circle" if probing else "refresh-cw")}</button>'
    )
    header = (
        '<div class="sb-header"><span class="sb-title">AI Usage</span>'
        f'<div class="sb-header-actions">{button}</div></div>'
    )
    if not installed:
        body = (
            f'<div class="sb-empty"><span class="sb-empty__icon">{icon("search")}</span>'
            f'<p class="sb-empty__title">{NONE_INSTALLED}</p>'
            '<p class="sb-empty__text">Install Claude Code or Codex, then refresh.</p></div>'
        )
    else:
        body = "".join(card(provider) for provider in installed)
    app.render(TILE, "flyout", header + body)


def render_all() -> None:
    render_tile()
    render_hover()
    render_flyout()


# --- Lifecycle ------------------------------------------------------------


def claude_interval() -> float:
    try:
        minutes = float(app.settings.get("claudeIntervalMinutes", DEFAULT_CLAUDE_MINUTES))
    except (TypeError, ValueError):
        app.log("warn", "claudeIntervalMinutes is not a number; using the default")
        minutes = DEFAULT_CLAUDE_MINUTES
    return max(60.0, minutes * 60.0)


@app.on_ready
def ready() -> None:
    state["installed"] = detect()
    render_all()  # placeholders first; tick() below fills them in


@app.every(TICK_SECONDS)
def tick() -> None:
    now = time.monotonic()
    installed = detect()  # a handful of stat() calls; an install or uninstall shows within a tick
    if installed != state["installed"]:
        state["installed"] = installed
        state["dirty"] = True
    if "codex" in installed and (
        not state["codex_polled"] or now - state["codex_polled"] >= CODEX_INTERVAL
    ):
        state["codex_polled"] = now
        read_codex()
        state["dirty"] = True
    if "claude" in installed and not state["probing"] and (
        not state["claude_polled"] or now - state["claude_polled"] >= claude_interval()
    ):
        probe_claude_async()
        state["dirty"] = True
    if state["dirty"]:
        state["dirty"] = False
        render_all()


@app.on_action(TILE, "refresh")
def refresh(action: str, value: object) -> None:
    state["installed"] = detect()
    if "codex" in state["installed"]:
        state["codex_polled"] = time.monotonic()
        read_codex()
    if "claude" in state["installed"] and not state["probing"]:
        probe_claude_async()
    render_all()  # shows the spinner right away; the probe result lands via tick()


@app.on_settings_changed
def settings_changed(settings: dict) -> None:
    state["installed"] = detect()
    if "claude" in state["installed"] and not state["probing"]:
        probe_claude_async()
    render_all()


if __name__ == "__main__":
    app.run()
