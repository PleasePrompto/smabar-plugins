"""Reads and writes the system clipboard as text: one read_text() and one
write_text() per platform, chosen at import.

read_text() returns the clipboard text, None when it holds no text, and raises
ClipboardError when the platform tool fails; write_text(text) puts text on the
clipboard or raises ClipboardError. MISSING_TOOL names the package to install
when no tool exists on this system (Linux only); both functions then always
raise. No bar imports, so the module loads without smabar.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable

TIMEOUT = 2.0  # a frozen clipboard owner must not stall the plugin for longer


class ClipboardError(RuntimeError):
    """The clipboard could not be read; str(error) names the cause."""


def _command(argv: list[str], empty_codes: tuple[int, ...] = ()) -> Callable[[], str | None]:
    """A reader around one CLI tool; exit codes in empty_codes mean "no text", not failure."""

    def read_text() -> str | None:
        try:
            done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"{argv[0]}: {exc}") from exc
        if done.returncode in empty_codes:
            return None
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", errors="replace").strip()
            raise ClipboardError(detail or f"{argv[0]} exited with {done.returncode}")
        return done.stdout.decode("utf-8", errors="replace") or None

    return read_text


def _writer(argv: list[str]) -> Callable[[str], None]:
    """A writer around one CLI tool. xclip, xsel and wl-copy fork a child that serves the
    selection until another program takes it; it must not inherit our pipes, or run()
    would wait for it."""

    def write_text(text: str) -> None:
        try:
            subprocess.run(
                argv,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=TIMEOUT,
                check=True,
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            raise ClipboardError(f"{argv[0]}: {exc}") from exc

    return write_text


def _windows_writer() -> Callable[[str], None]:
    """CF_UNICODETEXT through user32/kernel32; the system owns the handle after SetClipboardData."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    gmem_moveable, cf_unicodetext = 0x0002, 13

    def write_text(text: str) -> None:
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
        if not handle:
            raise ClipboardError("GlobalAlloc failed")
        ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            raise ClipboardError("another program holds the clipboard")
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(cf_unicodetext, handle):
                kernel32.GlobalFree(handle)
                raise ClipboardError("SetClipboardData failed")
        finally:
            user32.CloseClipboard()

    return write_text


def _windows_reader() -> Callable[[], str | None]:
    """CF_UNICODETEXT through user32/kernel32; no PowerShell process per poll."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    cf_unicodetext = 13

    def read_text() -> str | None:
        if not user32.IsClipboardFormatAvailable(cf_unicodetext):
            return None
        if not user32.OpenClipboard(None):
            return None  # another program holds the clipboard right now; the next poll retries
        try:
            handle = user32.GetClipboardData(cf_unicodetext)
            pointer = kernel32.GlobalLock(handle) if handle else None
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer) or None
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    return read_text


def _missing(tool: str) -> tuple[Callable[[], str | None], Callable[[str], None]]:
    def read_text() -> str | None:
        raise ClipboardError(f"no clipboard tool found; install {tool}")

    def write_text(text: str) -> None:
        raise ClipboardError(f"no clipboard tool found; install {tool}")

    return read_text, write_text


MISSING_TOOL = ""
if sys.platform == "win32":
    read_text, write_text = _windows_reader(), _windows_writer()
elif sys.platform == "darwin":
    # Without a UTF-8 locale pbpaste replaces non-ASCII characters with "?".
    os.environ.setdefault("LC_CTYPE", "UTF-8")
    read_text, write_text = _command(["pbpaste"]), _writer(["pbcopy"])
elif os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
    read_text = _command(["wl-paste", "--no-newline", "--type", "text"], empty_codes=(1,))
    write_text = _writer(["wl-copy"])
elif shutil.which("xclip"):
    read_text = _command(["xclip", "-o", "-selection", "clipboard"], empty_codes=(1,))
    write_text = _writer(["xclip", "-i", "-selection", "clipboard"])
elif shutil.which("xsel"):
    read_text = _command(["xsel", "--clipboard", "--output"])
    write_text = _writer(["xsel", "--clipboard", "--input"])
else:
    MISSING_TOOL = "wl-clipboard" if os.environ.get("WAYLAND_DISPLAY") else "xclip"
    read_text, write_text = _missing(MISSING_TOOL)
