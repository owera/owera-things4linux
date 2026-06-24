"""Application entry point: wires the store, sync engine and main window."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import config  # noqa: E402
from .db.store import Store  # noqa: E402
from .sync import credentials  # noqa: E402
from .sync.engine import SyncEngine  # noqa: E402
from .ui.login import LoginDialog  # noqa: E402
from .ui.window import MainWindow  # noqa: E402

_CSS = Path(__file__).with_name("resources") / "style.css"


class Things4LinuxApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=config.APPLICATION_ID)
        self.store: Store | None = None
        self.engine: SyncEngine | None = None

    def do_activate(self) -> None:
        win = self.props.active_window
        if win:
            win.present()
            return

        self._load_css()
        self.store = Store()
        self.engine = SyncEngine(self.store)
        win = MainWindow(self, self.store, self.engine)
        self.engine.set_callbacks(win.notify_changed, win.notify_status)
        win.present()
        self._bootstrap_sync(win)

    def _bootstrap_sync(self, win: MainWindow) -> None:
        engine = self.engine
        assert engine
        if engine.configured:
            engine.start()
            return
        creds = credentials.load()
        if creds and creds.history_key:
            engine.adopt_history_key(creds.history_key)
            engine.start()
        elif creds:
            threading.Thread(
                target=self._configure_worker,
                args=(creds.email, creds.password),
                daemon=True,
            ).start()
        else:
            LoginDialog(engine, on_success=engine.start).present(win)

    def _configure_worker(self, email: str, password: str) -> None:
        try:
            key = self.engine.configure(email, password)
            credentials.save(credentials.Credentials(email, password, key))
            GLib.idle_add(self.engine.start)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(
                self.props.active_window.notify_status, "auth-error", str(exc)
            )

    def _load_css(self) -> None:
        if not _CSS.exists():
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(_CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_shutdown(self) -> None:
        if self.engine:
            self.engine.stop()
        if self.store:
            self.store.close()
        Adw.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    app = Things4LinuxApplication()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
