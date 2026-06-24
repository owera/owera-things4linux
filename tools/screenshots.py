"""Render real Owera Things4Linux screenshots from crafted sample data.

Run headless:  xvfb-run -a python3 tools/screenshots.py

Captures the GTK window straight to PNG via the window's GskRenderer (no external
screenshot tool needed). Uses only invented data — never a real account.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

# Isolate config/data so we never touch a real install.
_tmp = tempfile.mkdtemp()
os.environ.setdefault("XDG_DATA_HOME", _tmp + "/data")
os.environ.setdefault("XDG_CONFIG_HOME", _tmp + "/config")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from things4linux import config  # noqa: E402
from things4linux.db.models import Area, Task  # noqa: E402
from things4linux.db.store import Store  # noqa: E402
from things4linux.sync.engine import SyncEngine  # noqa: E402
from things4linux.ui.window import MainWindow  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "screenshots")
W, H = 1100, 720

DAY = 86400


def midnight(offset_days: int = 0) -> int:
    lt = time.localtime()
    base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return int(base + offset_days * DAY)


def seed(store: Store) -> dict:
    """Populate a believable workspace and return a few key uuids."""
    work = store.add_area(Area(uuid=config.new_id(), title="Work"))
    personal = store.add_area(Area(uuid=config.new_id(), title="Personal"))
    store.add_area(Area(uuid=config.new_id(), title="Home"))

    t_work = store.ensure_tag("Work")
    t_errand = store.ensure_tag("Errand")
    t_waiting = store.ensure_tag("Waiting")

    # Projects
    website = store.add_task(
        Task(uuid=config.new_id(), title="Website Relaunch", type=1, area=work.uuid)
    )
    store.add_task(
        Task(uuid=config.new_id(), title="Trip to Japan", type=1, area=personal.uuid)
    )

    def todo(title, **kw):
        return store.add_task(Task(uuid=config.new_id(), title=title, **kw))

    # Today (daytime)
    a = todo("Review the new landing page copy", destination=1, scheduled_date=midnight())
    store.set_task_tags(a.uuid, [t_work.uuid])
    b = todo("Call the dentist", destination=1, scheduled_date=midnight(),
             deadline=midnight(2))
    store.set_task_tags(b.uuid, [t_errand.uuid])
    todo("Send invoice #1042", destination=1, scheduled_date=midnight())
    # Today (this evening)
    todo("Read a chapter of Designing Data-Intensive Applications",
         destination=1, scheduled_date=midnight(), evening=True)
    e = todo("Reply to Andrew about the contract", destination=1,
             scheduled_date=midnight(), evening=True)
    store.set_task_tags(e.uuid, [t_waiting.uuid])

    # Upcoming
    todo("Team retro", destination=1, scheduled_date=midnight(1))
    todo("Pay rent", destination=1, scheduled_date=midnight(3), deadline=midnight(3))
    todo("Flights to Tokyo", destination=1, scheduled_date=midnight(9))

    # Project tasks for Website Relaunch
    for i, title in enumerate([
        "Finalise the visual design",
        "Migrate the blog content",
        "Set up analytics",
        "QA on mobile",
    ]):
        p = todo(title, destination=1, project=website.uuid)
        if i == 0:
            store.set_task_tags(p.uuid, [t_work.uuid])

    # Anytime / Someday
    todo("Research standing desks", destination=1)
    todo("Learn to make ramen", destination=2)

    return {"project": website.uuid, "tag_work": t_work.uuid}


def capture(win: Gtk.Window, path: str) -> bool:
    """Render the window to a PNG via its GskRenderer."""
    paintable = Gtk.WidgetPaintable.new(win)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, W, H)
    node = snapshot.to_node()
    if node is None:
        return False
    native = win.get_native()
    renderer = native.get_renderer() if native else None
    if renderer is None:
        return False
    texture = renderer.render_texture(node, None)
    texture.save_to_png(path)
    return True


def pump(ms: int) -> None:
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


def _today(w, ids):
    w.search_btn.set_active(False)
    w.sidebar.select_view("builtin", "today")


def _project(w, ids):
    w.search_btn.set_active(False)
    w.sidebar.select_view("project", ids["project"])


def _tags(w, ids):
    w.search_btn.set_active(False)
    w.sidebar.select_view("tag", ids["tag_work"])


def _quick_find(w, ids):
    w.sidebar.select_view("builtin", "anytime")
    w.search_btn.set_active(True)
    w.search_entry.set_text("japan")


SHOTS = [
    # (filename, color_scheme, setup(win, ids))
    ("hero-dark.png", "dark", _today),
    ("today.png", "light", _today),
    ("project.png", "light", _project),
    ("tags.png", "light", _tags),
    ("quick-find.png", "light", _quick_find),
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    Adw.init()
    style = Adw.StyleManager.get_default()

    store = Store()
    ids = seed(store)

    app = Adw.Application(application_id="com.owera.Things4Linux.Shots",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    results = {}

    def on_activate(_a):
        # Load the app stylesheet + icons exactly like the real app.
        from things4linux.app import Things4LinuxApplication
        Things4LinuxApplication._load_css(app)  # reuse resource loading

        win = MainWindow(app, store, SyncEngine(store))
        win.set_default_size(W, H)
        win.present()

        def run_shots():
            for name, scheme, setup in SHOTS:
                style.set_color_scheme(
                    Adw.ColorScheme.FORCE_DARK if scheme == "dark"
                    else Adw.ColorScheme.FORCE_LIGHT
                )
                setup(win, ids)
                pump(450)  # let layout + theme settle
                path = os.path.join(OUT, name)
                ok = capture(win, path)
                size = os.path.getsize(path) if ok and os.path.exists(path) else 0
                results[name] = (ok, size)
                print(f"  {'ok ' if ok else 'FAIL'} {name}  ({size} bytes)")
            app.quit()

        GLib.timeout_add(300, lambda: (run_shots(), False)[1])

    app.connect("activate", on_activate)
    app.run([])

    failed = [n for n, (ok, sz) in results.items() if not ok or sz < 2000]
    print(f"\n{len(results)-len(failed)}/{len(results)} screenshots OK", flush=True)
    if failed:
        print("FAILED/empty:", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
