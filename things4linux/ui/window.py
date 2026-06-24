"""Main application window — the three-pane Things layout."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import config, views  # noqa: E402
from ..db import models  # noqa: E402
from ..db.models import Task  # noqa: E402
from ..db.store import Store  # noqa: E402
from ..sync.engine import SyncEngine  # noqa: E402
from .sidebar import Sidebar  # noqa: E402
from .taskdetail import TaskDialog, today_midnight  # noqa: E402
from .widgets import SectionRow, TaskRow  # noqa: E402

# title + which Store method backs each built-in view
_BUILTIN = {
    "inbox": ("Inbox", "inbox"),
    "today": ("Today", "today"),
    "upcoming": ("Upcoming", "upcoming"),
    "anytime": ("Anytime", "anytime"),
    "someday": ("Someday", "someday"),
    "logbook": ("Logbook", "logbook"),
    "trash": ("Trash", "trash"),
}
# default (destination, scheduled-today) for a to-do created inside each view
_ADD_DEFAULTS = {
    "inbox": (models.DEST_INBOX, False),
    "today": (models.DEST_ANYTIME, True),
    "anytime": (models.DEST_ANYTIME, False),
    "someday": (models.DEST_SOMEDAY, False),
}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: Store, engine: SyncEngine):
        super().__init__(application=app)
        self.store = store
        self.engine = engine
        self.current = ("builtin", "today")
        self.set_title(config.APP_NAME)
        self.set_default_size(1000, 680)

        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(240)
        self.set_content(self.split)

        # --- content (built before the sidebar, whose initial selection calls
        #     back into refresh_content and needs these widgets to exist) ---
        content_tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.title_label = Gtk.Label(label="Today", css_classes=["title"])
        header.set_title_widget(self.title_label)
        self.add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New To-Do")
        self.add_btn.connect("clicked", lambda *_: self.add_task())
        header.pack_start(self.add_btn)
        self.search_btn = Gtk.ToggleButton(
            icon_name="system-search-symbolic", tooltip_text="Quick Find (Ctrl+F)"
        )
        self.search_btn.connect("toggled", self._on_search_toggled)
        header.pack_start(self.search_btn)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Sync now")
        refresh_btn.connect("clicked", lambda *_: self.engine.trigger())
        header.pack_end(refresh_btn)
        self.empty_btn = Gtk.Button(label="Empty Trash")
        self.empty_btn.add_css_class("destructive-action")
        self.empty_btn.set_visible(False)
        self.empty_btn.connect("clicked", lambda *_: self._confirm_empty_trash())
        header.pack_end(self.empty_btn)
        content_tv.add_top_bar(header)

        # Quick Find search bar (revealed by the toggle button or Ctrl+F / typing)
        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry(hexpand=True, placeholder_text="Quick Find")
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.set_key_capture_widget(self)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode)
        self.search_entry.connect("search-changed", lambda *_: self.refresh_content())
        content_tv.add_top_bar(self.search_bar)

        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        content_tv.add_top_bar(self.banner)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("t4l-list")
        self.listbox.connect("row-activated", self._on_row_activated)
        self.placeholder = Gtk.Label(
            label="Nothing here yet", css_classes=["dim-label", "t4l-empty"]
        )
        self.listbox.set_placeholder(self.placeholder)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.listbox)
        scroller.set_vexpand(True)
        content_tv.set_content(scroller)

        self.split.set_content(Adw.NavigationPage(title="Today", child=content_tv))

        # --- sidebar (its initial row selection drives the first content load) ---
        self.sidebar = Sidebar(store, self._on_select)
        sidebar_tv = Adw.ToolbarView()
        sb_header = Adw.HeaderBar()
        sb_header.set_title_widget(Gtk.Label(label=config.APP_NAME, css_classes=["heading"]))
        sidebar_tv.add_top_bar(sb_header)
        sidebar_tv.set_content(self.sidebar)
        self.split.set_sidebar(Adw.NavigationPage(title=config.APP_NAME, child=sidebar_tv))

        self.refresh()

    # -- selection / refresh ----------------------------------------------------------
    def _on_select(self, kind: str, ref: str) -> None:
        self.current = ("builtin", ref) if kind == "builtin" else (kind, ref)
        self.refresh_content()

    def _query_current(self) -> list[Task]:
        kind, ref = self.current
        if kind == "builtin":
            method = _BUILTIN.get(ref, ("Today", "today"))[1]
            return getattr(self.store, method)()
        if kind == "area":
            return self.store.area_tasks(ref)
        if kind == "project":
            return self.store.project_tasks(ref)
        if kind == "tag":
            return self.store.tasks_with_tag(ref)
        return []

    def _current_title(self) -> str:
        kind, ref = self.current
        if kind == "builtin":
            return _BUILTIN.get(ref, ("Today",))[0]
        if kind == "area":
            a = next((a for a in self.store.areas() if a.uuid == ref), None)
            return a.title if a else "Area"
        if kind == "project":
            p = self.store.get_task(ref)
            return p.title if p else "Project"
        if kind == "tag":
            return self.store.tag_map().get(ref, "Tag")
        return ""

    def refresh(self) -> None:
        self.sidebar.refresh()
        self.refresh_content()

    def refresh_content(self) -> None:
        query = (
            self.search_entry.get_text().strip()
            if self.search_bar.get_search_mode()
            else ""
        )
        if query:
            self._populate_search(query)
            return

        title = self._current_title()
        self.title_label.set_text(title)
        # add button only makes sense in actionable lists (not logbook/trash/tag)
        kind, ref = self.current
        self.add_btn.set_visible(
            kind in ("area", "project")
            or (kind == "builtin" and ref not in ("logbook", "trash"))
        )

        tasks = self._query_current()
        self.empty_btn.set_visible(self.current == ("builtin", "trash") and bool(tasks))

        self._clear_list()
        self._tag_map = self.store.tag_map()
        kind, ref = self.current
        if kind == "builtin" and ref == "today":
            self._populate_today(tasks)
        elif kind == "builtin" and ref == "upcoming":
            self._populate_upcoming(tasks)
        else:
            for task in tasks:
                self._append_task(task)

    def _append_task(self, task: Task) -> None:
        self.listbox.append(
            TaskRow(task, self._on_toggle, self.open_task, self._tag_map)
        )

    def _populate_today(self, tasks: list[Task]) -> None:
        day, evening = views.split_today(tasks)
        for task in day:
            self._append_task(task)
        if evening:
            self.listbox.append(SectionRow("This Evening", "weather-clear-night-symbolic"))
            for task in evening:
                self._append_task(task)

    def _populate_upcoming(self, tasks: list[Task]) -> None:
        for header, group in views.group_upcoming(tasks):
            self.listbox.append(SectionRow(header))
            for task in group:
                self._append_task(task)

    def _populate_search(self, query: str) -> None:
        self.title_label.set_text("Quick Find")
        self.add_btn.set_visible(False)
        self.empty_btn.set_visible(False)
        self._clear_list()
        self._tag_map = self.store.tag_map()
        for task in self.store.search(query):
            self._append_task(task)

    # -- search controls --------------------------------------------------------------
    def _on_search_toggled(self, btn: Gtk.ToggleButton) -> None:
        self.search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self.search_entry.grab_focus()

    def _on_search_mode(self, bar: Gtk.SearchBar, _param) -> None:
        active = bar.get_search_mode()
        self.search_btn.set_active(active)
        if not active:
            self.search_entry.set_text("")
        self.refresh_content()

    def _clear_list(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

    # -- actions ----------------------------------------------------------------------
    def _on_row_activated(self, _box: Gtk.ListBox, row: TaskRow) -> None:
        row.open()

    def _on_toggle(self, task: Task, active: bool) -> None:
        if active and task.status == models.STATUS_TODO:
            self.store.complete_task(task.uuid)
        elif not active and task.status != models.STATUS_TODO:
            self.store.reopen_task(task.uuid)
        self.engine.trigger()
        self.refresh()

    def add_task(self) -> None:
        kind, ref = self.current
        dest, today = models.DEST_INBOX, False
        area = project = None
        if kind == "builtin":
            dest, today = _ADD_DEFAULTS.get(ref, (models.DEST_INBOX, False))
        elif kind == "area":
            area, dest = ref, models.DEST_ANYTIME
        elif kind == "project":
            project, dest = ref, models.DEST_ANYTIME
        task = Task(
            uuid=config.new_id(),
            destination=dest,
            scheduled_date=today_midnight() if today else None,
            area=area,
            project=project,
        )
        self.store.add_task(task)
        self.engine.trigger()
        self.refresh()
        self.open_task(task)

    def _confirm_empty_trash(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Empty Trash?",
            body="This permanently deletes the items in Trash. This can’t be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("empty", "Empty Trash")
        dialog.set_response_appearance("empty", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_empty_response)
        dialog.present(self)

    def _on_empty_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "empty":
            return
        self.store.empty_trash()
        self.engine.trigger()
        self.refresh()

    def open_task(self, task: Task) -> None:
        dialog = TaskDialog(self.store, task, self._after_edit)
        dialog.present(self)

    def _after_edit(self) -> None:
        self.engine.trigger()
        self.refresh()

    # -- engine callbacks (already marshalled onto the main loop) ---------------------
    def notify_changed(self) -> None:
        GLib.idle_add(self.refresh)

    def notify_status(self, state: str, detail: str) -> None:
        GLib.idle_add(self._apply_status, state, detail)

    def _apply_status(self, state: str, detail: str) -> bool:
        if state == "online":
            self.banner.set_revealed(False)
        elif state == "auth-error":
            self.banner.set_title("Sign-in failed — check your Things Cloud credentials.")
            self.banner.set_revealed(True)
        elif state == "offline":
            self.banner.set_title("Offline — changes will sync when reconnected.")
            self.banner.set_revealed(True)
        else:
            self.banner.set_title(f"Sync error: {detail}")
            self.banner.set_revealed(True)
        return False
