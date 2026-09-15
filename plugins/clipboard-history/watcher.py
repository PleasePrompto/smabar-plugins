"""Signals clipboard changes without reading the clipboard: one backend per platform.

start(signal, lost) tries the backends of this platform in order and returns the
name of the one that runs, or "" when none applies; the plugin then falls back to
reading the clipboard every pollSeconds. A backend runs on its own daemon thread
and calls signal() whenever the clipboard gets new content; it never reads the
text itself. lost(reason) is called once when a running backend dies (X server
gone, wl-paste exited) so the plugin can fall back to polling. Both callbacks
run on the watcher thread: keep them cheap and thread-safe. No bar imports.

- X11 and XWayland: an XFixes SetSelectionOwnerNotify event for CLIPBOARD (python-xlib).
  XWayland mirrors the Wayland clipboard, so this also covers GNOME Wayland.
- Wayland with the data-control protocol (wlroots compositors, KDE): `wl-paste --watch echo`
  prints one line per change. GNOME Mutter offers no data-control protocol on purpose.
- Windows: GetClipboardSequenceNumber compared twice a second: one syscall, the
  clipboard is never opened.
- macOS: NSPasteboard.changeCount compared twice a second (pyobjc). Apple offers
  no notification; every clipboard manager on the Mac does exactly this.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable

Signal = Callable[[], None]
Lost = Callable[[str], None]
COUNTER_INTERVAL = 0.5  # sequence-number and changeCount reads are an integer compare, not a clipboard read
WL_PASTE_PROBE = 1.0  # wl-paste --watch exits at once on a compositor without data-control


def _spawn(target: Callable[[], None], name: str) -> None:
    threading.Thread(target=target, name=name, daemon=True).start()


def _xfixes(signal: Signal, lost: Lost) -> str | None:
    if not os.environ.get("DISPLAY"):
        return None
    try:
        from Xlib import X, display
        from Xlib.ext import xfixes
    except ImportError:
        return None
    try:
        conn = display.Display()
        if not conn.has_extension("XFIXES") and conn.query_extension("XFIXES") is None:
            return None
        conn.xfixes_query_version()
        window = conn.screen().root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        conn.xfixes_select_selection_input(
            window, conn.get_atom("CLIPBOARD"), xfixes.XFixesSetSelectionOwnerNotifyMask
        )
        conn.flush()
    except Exception:  # noqa: BLE001 - python-xlib raises its own hierarchy; any failure here means "no XFixes"
        return None
    owner_notify = conn.extension_event.SetSelectionOwnerNotify

    def loop() -> None:
        try:
            while True:
                event = conn.next_event()
                if (event.type, event.sub_code) == owner_notify:
                    signal()
        except Exception as exc:  # noqa: BLE001 - the X connection is gone; the plugin polls from now on
            lost(f"XFixes: {exc}")

    _spawn(loop, "clipboard-xfixes")
    return "XFixes"


def _wl_paste(signal: Signal, lost: Lost) -> str | None:
    if not os.environ.get("WAYLAND_DISPLAY") or not shutil.which("wl-paste"):
        return None
    try:
        proc = subprocess.Popen(
            ["wl-paste", "--watch", "echo"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
    except OSError:
        return None
    try:
        proc.wait(timeout=WL_PASTE_PROBE)
    except subprocess.TimeoutExpired:
        pass  # still running: the compositor speaks data-control
    else:
        return None  # exited at once: no data-control protocol here (GNOME) or a wl-paste too old for it

    def loop() -> None:
        assert proc.stdout is not None
        for _line in proc.stdout:
            signal()
        lost(f"wl-paste --watch exited with {proc.wait()}")

    _spawn(loop, "clipboard-wl-paste")
    return "wl-paste --watch"


def _counter(read: Callable[[], int], name: str, signal: Signal) -> str:
    """Compares a cheap change counter twice a second and signals when it moved."""

    def loop() -> None:
        last = read()
        while True:
            time.sleep(COUNTER_INTERVAL)
            current = read()
            if current != last:
                last = current
                signal()

    _spawn(loop, f"clipboard-{name}")
    return name


def _windows(signal: Signal, lost: Lost) -> str | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    # ponytail: the counter instead of AddClipboardFormatListener, which needs a message-only
    # window plus a message loop; upgrade if one syscall every 0.5 s ever shows up anywhere.
    return _counter(user32.GetClipboardSequenceNumber, "GetClipboardSequenceNumber", signal)


def _macos(signal: Signal, lost: Lost) -> str | None:
    try:
        from AppKit import NSPasteboard
    except ImportError:
        return None
    board = NSPasteboard.generalPasteboard()
    return _counter(board.changeCount, "NSPasteboard.changeCount", signal)


def start(signal: Signal, lost: Lost) -> str:
    """Starts the first backend that works on this system and returns its name, or ""."""
    if sys.platform == "win32":
        backends = (_windows,)
    elif sys.platform == "darwin":
        backends = (_macos,)
    else:
        backends = (_wl_paste, _xfixes)
    for backend in backends:
        name = backend(signal, lost)
        if name:
            return name
    return ""
