"""Platform inhibitors and session timer math for Keep Awake. No SDK here, so
this module imports and tests without a running bar.

One class per platform, each with start() -> mechanism label and stop().
Every mechanism is bound to this process: the Windows execution state dies
with its thread, caffeinate waits for our pid, and every Linux child waits for
our pid too (tail --pid), so nothing outlives the plugin even after a hard kill.
"""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

MAX_MINUTES = 1440
WHO = "smabar"
WHY = "Keep Awake"
XDG_RESET_SECONDS = 50
# The distro python is the one with PyGObject; uv's interpreter never has it.
SYSTEM_PATH = "/usr/bin:/usr/local/bin:/bin"
STARTUP_GRACE = 0.2

SYSTEMD = "systemd-inhibit"
GNOME = "gnome-session-inhibit"
DBUS = "org.freedesktop.ScreenSaver"
XDG = "xdg-screensaver"

# SetThreadExecutionState flags (winbase.h).
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

Which = Callable[..., str | None]
Log = Callable[[str], None]


class BackendError(Exception):
    """An inhibitor could not be started; the message is meant for the user."""


class Backend(Protocol):
    def start(self) -> str: ...

    def stop(self) -> None: ...


def end_at(now: float, minutes: int) -> float | None:
    """Epoch seconds when a session ends; 0 minutes means until switched off."""
    return now + minutes * 60 if minutes > 0 else None


def remaining_minutes(end: float | None, now: float) -> int | None:
    """Whole minutes left, rounded up so a session never reads as over early."""
    return None if end is None else max(0, math.ceil((end - now) / 60))


def ended(end: float | None, now: float) -> bool:
    return end is not None and now >= end


def wait_for_me() -> list[str]:
    """A command that exits when this plugin's process is gone."""
    return ["tail", "--pid", str(os.getpid()), "-f", "/dev/null"]


def spawn(cmd: list[str]) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise BackendError(f"{cmd[0]}: {exc.strerror or exc}") from exc


def stop_child(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


def last_error(proc: subprocess.Popen[str], fallback: str) -> str:
    """The last stderr line of a child that has exited, else the fallback."""
    text = proc.stderr.read().strip() if proc.stderr and proc.poll() is not None else ""
    return text.splitlines()[-1] if text else fallback


def expect_alive(proc: subprocess.Popen[str], name: str) -> None:
    """A wrapper that fails does so at once; give it a moment, then check."""
    time.sleep(STARTUP_GRACE)
    if proc.poll() is not None:
        message = last_error(proc, f"{name} exited with status {proc.returncode}")
        stop_child(proc)
        raise BackendError(message)


class WindowsBackend:
    """SetThreadExecutionState is per thread, so a dedicated thread holds the
    flags and clears them again with ES_CONTINUOUS on stop."""

    def __init__(self) -> None:
        self._release = threading.Event()
        self._thread: threading.Thread | None = None
        self._previous = 0

    def start(self) -> str:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
        self._release.clear()
        applied = threading.Event()

        def hold() -> None:
            self._previous = kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
            applied.set()
            self._release.wait()
            kernel32.SetThreadExecutionState(ES_CONTINUOUS)

        self._thread = threading.Thread(target=hold, name="keep-awake", daemon=True)
        self._thread.start()
        applied.wait(5)
        if not self._previous:
            self.stop()
            raise BackendError("SetThreadExecutionState failed")
        return "SetThreadExecutionState"

    def stop(self) -> None:
        self._release.set()
        if self._thread:
            self._thread.join(5)
            self._thread = None


class MacBackend:
    """caffeinate holds display, idle, disk and system assertions and releases
    them itself when our pid exits (-w)."""

    def __init__(self, which: Which) -> None:
        self.which = which
        self.proc: subprocess.Popen[str] | None = None

    def start(self) -> str:
        if not self.which("caffeinate"):
            raise BackendError("caffeinate not found")
        self.proc = spawn(["caffeinate", "-dims", "-w", str(os.getpid())])
        expect_alive(self.proc, "caffeinate")
        return "caffeinate"

    def stop(self) -> None:
        if self.proc:
            stop_child(self.proc)
            self.proc = None


class LinuxPlan(NamedTuple):
    sleep: bool  # systemd-inhibit blocks sleep (and idle where logind acts on it)
    idle: tuple[str, ...]  # screen-idle inhibitors to try, in preference order


def plan_linux(which: Which, display: str) -> LinuxPlan:
    """What this Linux desktop offers. xdg-screensaver is X11 only and its
    reset is a no-op on Cinnamon, hence the D-Bus helper before it."""
    idle: list[str] = []
    if which(GNOME):
        idle.append(GNOME)
    if which("python3", path=SYSTEM_PATH):
        idle.append(DBUS)
    if display and which(XDG):
        idle.append(XDG)
    return LinuxPlan(sleep=bool(which(SYSTEMD)), idle=tuple(idle))


class LinuxBackend:
    """systemd-inhibit for sleep plus the first idle inhibitor that comes up."""

    def __init__(self, plan: LinuxPlan, helper: Path, which: Which, log: Log) -> None:
        self.plan = plan
        self.helper = helper
        self.which = which
        self.log = log
        self.procs: list[subprocess.Popen[str]] = []
        self._release = threading.Event()

    def start(self) -> str:
        if not self.plan.sleep and not self.plan.idle:
            raise BackendError("no inhibitor found: install systemd, gnome-session, PyGObject or xdg-utils")
        active: list[str] = []
        if self.plan.sleep:
            self.procs.append(
                spawn(
                    [
                        SYSTEMD,
                        "--what=idle:sleep",
                        f"--who={WHO}",
                        f"--why={WHY}",
                        "--mode=block",
                        *wait_for_me(),
                    ]
                )
            )
            expect_alive(self.procs[-1], SYSTEMD)
            active.append(SYSTEMD)
        for name in self.plan.idle:
            try:
                self._start_idle(name)
            except BackendError as exc:
                self.log(f"{name} not usable: {exc}")
                continue
            active.append(name)
            break
        else:
            if not active:
                raise BackendError("no idle inhibitor could be started")
            self.log("screen idle is not inhibited, only sleep")
        return " + ".join(active)

    def _start_idle(self, name: str) -> None:
        if name == GNOME:
            proc = spawn([GNOME, "--app-id", WHO, "--reason", WHY, "--inhibit", "idle", *wait_for_me()])
            expect_alive(proc, GNOME)
            self.procs.append(proc)
        elif name == DBUS:
            python = self.which("python3", path=SYSTEM_PATH) or "python3"
            proc = spawn([python, str(self.helper), str(os.getpid())])
            line = proc.stdout.readline() if proc.stdout else ""
            if not line.startswith("ok"):
                try:
                    proc.wait(2)
                except subprocess.TimeoutExpired:
                    pass
                message = last_error(proc, "the inhibit helper gave no answer")
                stop_child(proc)
                raise BackendError(message)
            self.procs.append(proc)
        else:
            self._reset()
            self._release.clear()
            threading.Thread(target=self._reset_loop, name="xdg-reset", daemon=True).start()

    def _reset(self) -> None:
        result = subprocess.run(
            [XDG, "reset"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10
        )
        if result.returncode:
            text = result.stderr.strip()
            raise BackendError(text.splitlines()[-1] if text else f"{XDG} reset failed")

    def _reset_loop(self) -> None:
        while not self._release.wait(XDG_RESET_SECONDS):
            try:
                self._reset()
            except (BackendError, subprocess.TimeoutExpired) as exc:
                self.log(f"{XDG} reset failed: {exc}")

    def stop(self) -> None:
        self._release.set()
        for proc in self.procs:
            stop_child(proc)
        self.procs.clear()


def choose_backend(system: str, which: Which, display: str, helper: Path, log: Log) -> Backend:
    """Pick the backend for platform.system(); nothing starts until start()."""
    if system == "Windows":
        return WindowsBackend()
    if system == "Darwin":
        return MacBackend(which)
    return LinuxBackend(plan_linux(which, display), helper, which, log)
