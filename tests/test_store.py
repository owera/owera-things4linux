import os
import tempfile
import time
import unittest

from things4linux import config
from things4linux.db import models
from things4linux.db.models import Area, Task
from things4linux.db.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _add(self, **kw) -> Task:
        task = Task(uuid=config.new_id(), **kw)
        return self.store.add_task(task)

    def test_inbox_and_queue(self):
        self._add(title="A")
        self.assertEqual([t.title for t in self.store.inbox()], ["A"])
        # one create queued
        self.assertEqual(len(self.store.pending_changes()), 1)

    def test_today_vs_upcoming(self):
        self._add(title="now", destination=models.DEST_ANYTIME, scheduled_date=int(time.time()))
        self._add(
            title="later",
            destination=models.DEST_ANYTIME,
            scheduled_date=int(time.time()) + 5 * 86400,
        )
        self.assertEqual([t.title for t in self.store.today()], ["now"])
        self.assertEqual([t.title for t in self.store.upcoming()], ["later"])

    def test_today_excludes_someday(self):
        past = int(time.time()) - 86400
        self._add(title="anytime", destination=models.DEST_ANYTIME, scheduled_date=past)
        # Someday item carrying a leftover scheduled date must not leak into Today.
        self._add(title="someday", destination=models.DEST_SOMEDAY, scheduled_date=past)
        self.assertEqual([t.title for t in self.store.today()], ["anytime"])

    def test_complete_moves_to_logbook(self):
        t = self._add(title="done me")
        self.store.complete_task(t.uuid)
        self.assertEqual(self.store.inbox(), [])
        self.assertEqual([t.title for t in self.store.logbook()], ["done me"])

    def test_areas_and_projects(self):
        area = self.store.add_area(Area(uuid=config.new_id(), title="Work"))
        proj = self._add(title="Launch", type=models.TYPE_PROJECT, area=area.uuid)
        self.assertEqual([a.title for a in self.store.areas()], ["Work"])
        self.assertEqual([p.title for p in self.store.projects(area.uuid)], ["Launch"])
        # task inside the project
        self._add(title="step 1", project=proj.uuid, destination=models.DEST_ANYTIME)
        self.assertEqual([t.title for t in self.store.project_tasks(proj.uuid)], ["step 1"])

    def test_search(self):
        self._add(title="Buy oat milk")
        self._add(title="Call dentist", notes="ask about the appointment")
        self._add(title="Buy bread")
        trashed = self._add(title="Buy milk old")
        self.store.trash_task(trashed.uuid)
        # term in title
        self.assertEqual([t.title for t in self.store.search("dentist")], ["Call dentist"])
        # term in notes
        self.assertEqual([t.title for t in self.store.search("appointment")], ["Call dentist"])
        # AND across terms, trashed excluded
        self.assertEqual([t.title for t in self.store.search("buy milk")], ["Buy oat milk"])
        # empty query -> nothing
        self.assertEqual(self.store.search("   "), [])

    def test_apply_remote_does_not_queue(self):
        uuid = config.new_id()
        self.store.apply_remote("task", uuid, 0, {"title": "remote", "destination": 2})
        self.assertEqual([t.title for t in self.store.someday()], ["remote"])
        self.assertEqual(self.store.pending_changes(), [])

    def test_remote_does_not_clobber_dirty(self):
        t = self._add(title="local edit")
        # row is dirty (un-pushed); a remote update should be ignored for now
        self.store.apply_remote("task", t.uuid, 1, {"title": "server wins?"})
        self.assertEqual(self.store.get_task(t.uuid).title, "local edit")


if __name__ == "__main__":
    unittest.main()
