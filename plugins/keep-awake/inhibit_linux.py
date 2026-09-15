#!/usr/bin/env python3
"""Hold a freedesktop screensaver inhibit for as long as this process lives.

plugin.py starts this with the distro's python3, which has PyGObject on every
GNOME, Cinnamon and MATE desktop. It prints "ok <cookie>" once the inhibit is
registered and then waits: the inhibit is released when the D-Bus connection
closes, that is when this process ends. It also ends itself when the parent
pid given as the only argument disappears.
"""

import os
import sys

from gi.repository import Gio, GLib


def main(parent: int) -> int:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync(
        "org.freedesktop.ScreenSaver",
        "/org/freedesktop/ScreenSaver",
        "org.freedesktop.ScreenSaver",
        "Inhibit",
        GLib.Variant("(ss)", ("smabar", "Keep Awake")),
        GLib.VariantType("(u)"),
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    print("ok", reply.unpack()[0], flush=True)
    loop = GLib.MainLoop()

    def parent_alive() -> bool:
        if os.getppid() != parent:
            loop.quit()
        return True

    GLib.timeout_add_seconds(2, parent_alive)
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
