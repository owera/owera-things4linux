"""Best-effort animated demo GIF for the README.

Renders a sequence of UI states to PNG frames (deterministic, via the GTK
renderer) and assembles them into an optimised GIF with ffmpeg. Run headless:

    xvfb-run -a python3 tools/record_demo.py

Falls back gracefully (non-zero exit, no GIF) if ffmpeg or capture misbehaves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp()
os.environ.setdefault("XDG_DATA_HOME", _tmp + "/data")
os.environ.setdefault("XDG_CONFIG_HOME", _tmp + "/config")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the tools/ dir

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from things4linux.sync.engine import SyncEngine  # noqa: E402
from things4linux.ui.window import MainWindow  # noqa: E402
import screenshots as shots  # reuse seed()/capture()/pump()  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "screenshots", "demo.gif")
W, H = shots.W, shots.H


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found — skipping GIF")
        return 1

    Adw.init()
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    from things4linux.db.store import Store

    store = Store()
    ids = shots.seed(store)
    # uuid of a Today item we'll complete on camera
    to_complete = next(
        (t.uuid for t in store.today() if "invoice" in t.title.lower()), None
    )

    app = Adw.Application(application_id="com.owera.Things4Linux.Demo",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    frames_dir = tempfile.mkdtemp()
    state = {"i": 0, "ok": True}

    def grab(win, repeat=1):
        for _ in range(repeat):
            path = os.path.join(frames_dir, f"frame_{state['i']:03d}.png")
            if not shots.capture(win, path):
                state["ok"] = False
            state["i"] += 1

    def on_activate(_a):
        from things4linux.app import Things4LinuxApplication
        Things4LinuxApplication._load_css(app)
        win = MainWindow(app, store, SyncEngine(store))
        win.set_default_size(W, H)
        win.present()

        def run():
            win.sidebar.select_view("builtin", "today"); shots.pump(400); grab(win, 3)
            if to_complete:
                store.complete_task(to_complete); win.refresh(); shots.pump(350); grab(win, 3)
            win.sidebar.select_view("builtin", "upcoming"); shots.pump(400); grab(win, 3)
            win.sidebar.select_view("project", ids["project"]); shots.pump(400); grab(win, 3)
            win.sidebar.select_view("tag", ids["tag_work"]); shots.pump(400); grab(win, 3)
            win.sidebar.select_view("builtin", "anytime")
            win.search_btn.set_active(True)
            for q in ("j", "ja", "jap", "japan"):
                win.search_entry.set_text(q); shots.pump(250); grab(win, 1)
            shots.pump(300); grab(win, 3)
            win.search_btn.set_active(False)
            win.sidebar.select_view("builtin", "today"); shots.pump(300); grab(win, 3)
            app.quit()

        GLib.timeout_add(300, lambda: (run(), False)[1])

    app.connect("activate", on_activate)
    app.run([])

    n = state["i"]
    print(f"captured {n} frames (ok={state['ok']})")
    if not state["ok"] or n < 8:
        print("frame capture incomplete — skipping GIF")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    vf = ("scale=900:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3")
    cmd = ["ffmpeg", "-y", "-framerate", "5", "-i",
           os.path.join(frames_dir, "frame_%03d.png"), "-vf", vf, "-loop", "0", OUT]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg failed:\n", r.stderr[-800:])
        return 1
    size = os.path.getsize(OUT)
    print(f"wrote {OUT} ({size//1024} KiB, {n} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
