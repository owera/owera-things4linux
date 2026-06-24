"""Task detail editor, shown as an Adw.Dialog. Edits persist live to the store."""

from __future__ import annotations

import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..db import models  # noqa: E402
from ..db.store import Store  # noqa: E402
from ..db.models import Task  # noqa: E402

# "When" options in display order, mapped to (destination, schedules_today).
_WHEN = [
    ("Inbox", models.DEST_INBOX, False),
    ("Today", models.DEST_ANYTIME, True),
    ("Anytime", models.DEST_ANYTIME, False),
    ("Someday", models.DEST_SOMEDAY, False),
]


def today_midnight() -> int:
    lt = time.localtime()
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def _when_index(task: Task) -> int:
    if task.destination == models.DEST_SOMEDAY:
        return 3
    if task.destination == models.DEST_ANYTIME:
        return 1 if task.scheduled_date else 2
    return 0


class TaskDialog(Adw.Dialog):
    def __init__(self, store: Store, task: Task, on_changed: Callable[[], None]):
        super().__init__()
        self.store = store
        self.task = task
        self.on_changed = on_changed
        self._loading = True
        self.set_title("To-Do")
        self.set_content_width(440)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)

        page = Adw.PreferencesPage()
        toolbar.set_content(page)

        group = Adw.PreferencesGroup()
        page.add(group)

        self.title_row = Adw.EntryRow(title="Title")
        self.title_row.set_text(task.title)
        self.title_row.connect("changed", self._on_title)
        group.add(self.title_row)

        # Notes
        notes_group = Adw.PreferencesGroup(title="Notes")
        page.add(notes_group)
        self.notes = Gtk.TextView()
        self.notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.notes.set_size_request(-1, 100)
        self.notes.add_css_class("t4l-notes")
        self.notes.get_buffer().set_text(task.notes or "")
        self.notes.get_buffer().connect("changed", self._on_notes)
        frame = Gtk.Frame()
        frame.set_child(self.notes)
        notes_group.add(frame)

        # Scheduling
        sched = Adw.PreferencesGroup(title="Schedule")
        page.add(sched)

        self.when = Adw.ComboRow(title="When")
        self.when.set_model(Gtk.StringList.new([w[0] for w in _WHEN]))
        self.when.set_selected(_when_index(task))
        self.when.connect("notify::selected", self._on_when)
        sched.add(self.when)

        self.evening = Adw.SwitchRow(title="This Evening")
        self.evening.set_active(task.evening)
        self.evening.connect("notify::active", self._on_evening)
        sched.add(self.evening)

        self.deadline_row = Adw.ActionRow(title="Deadline")
        self._deadline_btn = Gtk.MenuButton(valign=Gtk.Align.CENTER)
        self._deadline_btn.set_label(self._deadline_label())
        self._deadline_btn.set_popover(self._make_calendar_popover())
        self.deadline_row.add_suffix(self._deadline_btn)
        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", lambda *_: self._set_deadline(None))
        self.deadline_row.add_suffix(clear_btn)
        sched.add(self.deadline_row)

        # Actions
        actions = Adw.PreferencesGroup()
        page.add(actions)
        box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        complete = Gtk.Button(label="Complete")
        complete.add_css_class("suggested-action")
        complete.connect("clicked", self._on_complete)
        box.append(complete)
        trash = Gtk.Button(label="Move to Trash")
        trash.add_css_class("destructive-action")
        trash.connect("clicked", self._on_trash)
        box.append(trash)
        actions.add(box)

        self._loading = False

    # -- persistence helpers ----------------------------------------------------------
    def _save(self, changes: dict) -> None:
        if self._loading:
            return
        self.store.update_task(self.task.uuid, changes)
        # keep our local copy current so re-reads in the same session are correct
        for k, v in changes.items():
            setattr(self.task, k, v)
        self.on_changed()

    def _on_title(self, row: Adw.EntryRow) -> None:
        self._save({"title": row.get_text()})

    def _on_notes(self, buf: Gtk.TextBuffer) -> None:
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self._save({"notes": text})

    def _on_when(self, row: Adw.ComboRow, _param) -> None:
        _label, dest, today = _WHEN[row.get_selected()]
        changes = {"destination": dest}
        changes["scheduled_date"] = today_midnight() if today else None
        self._save(changes)

    def _on_evening(self, row: Adw.SwitchRow, _param) -> None:
        self._save({"evening": row.get_active()})

    def _on_complete(self, _btn) -> None:
        self.store.complete_task(self.task.uuid)
        self.on_changed()
        self.close()

    def _on_trash(self, _btn) -> None:
        self.store.trash_task(self.task.uuid)
        self.on_changed()
        self.close()

    # -- deadline calendar ------------------------------------------------------------
    def _deadline_label(self) -> str:
        if self.task.deadline:
            return time.strftime("%-d %b %Y", time.localtime(self.task.deadline))
        return "Add Deadline"

    def _make_calendar_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        cal = Gtk.Calendar()
        if self.task.deadline:
            lt = time.localtime(self.task.deadline)
            from gi.repository import GLib

            cal.select_day(GLib.DateTime.new_local(lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0))
        cal.connect("day-selected", self._on_calendar_day, pop)
        pop.set_child(cal)
        return pop

    def _on_calendar_day(self, cal: Gtk.Calendar, pop: Gtk.Popover) -> None:
        dt = cal.get_date()
        epoch = int(
            time.mktime((dt.get_year(), dt.get_month(), dt.get_day_of_month(), 0, 0, 0, 0, 0, -1))
        )
        self._set_deadline(epoch)
        pop.popdown()

    def _set_deadline(self, epoch: int | None) -> None:
        self.task.deadline = epoch
        self._deadline_btn.set_label(self._deadline_label())
        self._save({"deadline": epoch})
