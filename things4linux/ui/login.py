"""First-run login dialog. Runs the (blocking) Things Cloud login off the main
thread and reports success/failure back via GLib.idle_add."""

from __future__ import annotations

import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..sync import credentials  # noqa: E402
from ..sync.engine import SyncEngine  # noqa: E402


class LoginDialog(Adw.Dialog):
    def __init__(self, engine: SyncEngine, on_success: Callable[[], None]):
        super().__init__()
        self.engine = engine
        self.on_success = on_success
        self.set_title("Sign in to Things Cloud")
        self.set_content_width(420)
        self.set_can_close(False)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar(show_end_title_buttons=False))
        self.set_child(toolbar)

        page = Adw.PreferencesPage()
        toolbar.set_content(page)
        group = Adw.PreferencesGroup(
            description="Use your Things Cloud account. This is an unofficial, "
            "reverse-engineered client — consider testing with a secondary account."
        )
        page.add(group)

        self.email = Adw.EntryRow(title="Email")
        self.email.set_input_purpose(Gtk.InputPurpose.EMAIL)
        group.add(self.email)
        self.password = Adw.PasswordEntryRow(title="Password")
        group.add(self.password)

        self.error = Gtk.Label(xalign=0)
        self.error.add_css_class("error")
        self.error.set_visible(False)
        group.add(self.error)

        btn_box = Gtk.Box(halign=Gtk.Align.CENTER, spacing=8, margin_top=8)
        self.spinner = Gtk.Spinner()
        btn_box.append(self.spinner)
        self.login_btn = Gtk.Button(label="Sign In")
        self.login_btn.add_css_class("suggested-action")
        self.login_btn.add_css_class("pill")
        self.login_btn.connect("clicked", self._on_login)
        btn_box.append(self.login_btn)
        group.add(btn_box)

    def _on_login(self, _btn) -> None:
        email = self.email.get_text().strip()
        password = self.password.get_text()
        if not email or not password:
            self._show_error("Please enter your email and password.")
            return
        self.error.set_visible(False)
        self.login_btn.set_sensitive(False)
        self.spinner.start()
        threading.Thread(
            target=self._login_worker, args=(email, password), daemon=True
        ).start()

    def _login_worker(self, email: str, password: str) -> None:
        try:
            key = self.engine.configure(email, password)
            credentials.save(credentials.Credentials(email, password, key))
            GLib.idle_add(self._on_done, None)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            GLib.idle_add(self._on_done, str(exc))

    def _on_done(self, error: str | None) -> bool:
        self.spinner.stop()
        self.login_btn.set_sensitive(True)
        if error:
            self._show_error(error)
            return False
        self.set_can_close(True)
        self.close()
        self.on_success()
        return False

    def _show_error(self, msg: str) -> None:
        self.error.set_text(msg)
        self.error.set_visible(True)
