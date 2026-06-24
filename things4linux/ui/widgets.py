"""Reusable widgets — primarily the task row shown in every list."""

from __future__ import annotations

import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..db import models  # noqa: E402
from ..db.models import Task  # noqa: E402


def _format_date(epoch: int | None) -> str:
    if not epoch:
        return ""
    return time.strftime("%-d %b", time.localtime(epoch))


class SectionRow(Gtk.ListBoxRow):
    """A non-interactive header dividing a list (e.g. 'This Evening', a date)."""

    def __init__(self, title: str, icon: str | None = None):
        super().__init__()
        self.set_selectable(False)
        self.set_activatable(False)
        self.add_css_class("t4l-section")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(14)
        box.set_margin_bottom(4)
        box.set_margin_start(12)
        box.set_margin_end(12)
        if icon:
            box.append(Gtk.Image.new_from_icon_name(icon))
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("t4l-section-label")
        box.append(label)
        self.set_child(box)


class TaskRow(Gtk.ListBoxRow):
    """A single to-do: round check button, title, and an optional deadline tag."""

    def __init__(
        self,
        task: Task,
        on_toggle: Callable[[Task, bool], None],
        on_open: Callable[[Task], None],
        tag_map: dict[str, str] | None = None,
    ):
        super().__init__()
        self.task = task
        self._on_open = on_open
        tag_map = tag_map or {}
        self.add_css_class("t4l-task-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        self.check = Gtk.CheckButton()
        self.check.add_css_class("t4l-check")
        self.check.set_valign(Gtk.Align.CENTER)
        self.check.set_active(task.status != models.STATUS_TODO)
        self.check.connect("toggled", self._on_check)
        box.append(self.check)

        title = Gtk.Label(label=task.title or "New To-Do", xalign=0)
        title.set_hexpand(True)
        title.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        if task.status != models.STATUS_TODO:
            title.add_css_class("t4l-done")
        box.append(title)

        for tag_uuid in task.tags:
            name = tag_map.get(tag_uuid)
            if not name:
                continue
            chip = Gtk.Label(label=name)
            chip.add_css_class("t4l-tag-chip")
            chip.set_valign(Gtk.Align.CENTER)
            box.append(chip)

        if task.deadline:
            tag = Gtk.Label(label=f"⚑ {_format_date(task.deadline)}")
            tag.add_css_class("t4l-deadline")
            tag.set_valign(Gtk.Align.CENTER)
            box.append(tag)

        self.set_child(box)
        self._toggle_cb = on_toggle

    def _on_check(self, button: Gtk.CheckButton) -> None:
        # Defer so the check animation is visible before the list refreshes.
        GLib.timeout_add(120, self._fire_toggle, button.get_active())

    def _fire_toggle(self, active: bool) -> bool:
        self._toggle_cb(self.task, active)
        return False

    def open(self) -> None:
        self._on_open(self.task)
