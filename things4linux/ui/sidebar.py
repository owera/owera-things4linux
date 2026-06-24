"""Navigation sidebar: built-in views followed by Areas and their Projects."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..db.store import Store  # noqa: E402

# (view_id, label, symbolic icon)
BUILTIN_VIEWS = [
    ("inbox", "Inbox", "mail-inbox-symbolic"),
    ("today", "Today", "starred-symbolic"),
    ("upcoming", "Upcoming", "x-office-calendar-symbolic"),
    ("anytime", "Anytime", "view-list-ordered-symbolic"),
    ("someday", "Someday", "preferences-system-time-symbolic"),
    ("logbook", "Logbook", "object-select-symbolic"),
    ("trash", "Trash", "user-trash-symbolic"),
]


class _Row(Gtk.ListBoxRow):
    def __init__(self, kind: str, ref: str, label: str, icon: str | None, indent: int = 0):
        super().__init__()
        self.kind = kind  # "builtin" | "area" | "project" | "header"
        self.ref = ref
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        box.set_margin_start(8 + indent * 16)
        box.set_margin_end(8)
        if icon:
            img = Gtk.Image.new_from_icon_name(icon)
            box.append(img)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_hexpand(True)
        if kind == "header":
            lbl.add_css_class("dim-label")
            lbl.add_css_class("caption-heading")
            self.set_selectable(False)
            self.set_activatable(False)
        box.append(lbl)
        self.badge = Gtk.Label()
        self.badge.add_css_class("t4l-badge")
        box.append(self.badge)
        self.set_child(box)

    def set_badge(self, n: int) -> None:
        self.badge.set_text(str(n) if n else "")


class Sidebar(Gtk.ScrolledWindow):
    def __init__(self, store: Store, on_select: Callable[[str, str], None]):
        super().__init__()
        self.store = store
        self.on_select = on_select
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        self.set_child(self.listbox)

        self._builtin_rows: dict[str, _Row] = {}
        self.refresh()

    def _on_row_selected(self, _box: Gtk.ListBox, row: _Row | None) -> None:
        if row is None or row.kind == "header":
            return
        self.on_select(row.kind, row.ref)

    def _clear(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt

    def refresh(self) -> None:
        selected = self.listbox.get_selected_row()
        sel_key = (selected.kind, selected.ref) if selected else ("builtin", "today")
        self._clear()
        self._builtin_rows.clear()

        for view_id, label, icon in BUILTIN_VIEWS:
            row = _Row("builtin", view_id, label, icon)
            self._builtin_rows[view_id] = row
            self.listbox.append(row)

        areas = self.store.areas()
        projects_no_area = [p for p in self.store.projects() if not p.area]
        if areas or projects_no_area:
            self.listbox.append(_Row("header", "", "Areas", None))
        for area in areas:
            self.listbox.append(_Row("area", area.uuid, area.title or "Area", "folder-symbolic"))
            for proj in self.store.projects(area.uuid):
                self.listbox.append(
                    _Row("project", proj.uuid, proj.title or "Project", "view-list-symbolic", indent=1)
                )
        for proj in projects_no_area:
            self.listbox.append(
                _Row("project", proj.uuid, proj.title or "Project", "view-list-symbolic")
            )

        # badges for inbox/today
        counts = self.store.counts()
        if "inbox" in self._builtin_rows:
            self._builtin_rows["inbox"].set_badge(counts.get("inbox", 0))
        if "today" in self._builtin_rows:
            self._builtin_rows["today"].set_badge(counts.get("today", 0))

        # restore selection
        self._reselect(sel_key)

    def _reselect(self, key: tuple[str, str]) -> None:
        row = self.listbox.get_first_child()
        while row is not None:
            if isinstance(row, _Row) and (row.kind, row.ref) == key:
                self.listbox.select_row(row)
                return
            row = row.get_next_sibling()
        if "today" in self._builtin_rows:
            self.listbox.select_row(self._builtin_rows["today"])
