import os
import tempfile
import unittest

from things4linux import config
from things4linux.db import models
from things4linux.db.models import Area, Task
from things4linux.db.store import Store
from things4linux.sync import serde
from things4linux.sync.engine import SyncEngine

from .fake_cloud import FakeCloud


class TagTest(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _task(self, **kw) -> Task:
        return self.store.add_task(Task(uuid=config.new_id(), **kw))

    def test_ensure_tag_is_idempotent(self):
        a = self.store.ensure_tag("Work")
        b = self.store.ensure_tag("work")  # case-insensitive match
        self.assertEqual(a.uuid, b.uuid)
        self.assertEqual([t.title for t in self.store.tags()], ["Work"])

    def test_set_task_tags_attaches_and_queues(self):
        t = self._task(title="tagged")
        work = self.store.ensure_tag("Work")
        self.store.set_task_tags(t.uuid, [work.uuid])
        reread = self.store.get_task(t.uuid)
        self.assertEqual(reread.tags, [work.uuid])
        self.assertEqual(self.store.tag_map()[work.uuid], "Work")
        # a tag create and a task edit are queued
        kinds = [(r["kind"], r["op"]) for r in self.store.pending_changes()]
        self.assertIn(("tag", 0), kinds)
        self.assertIn(("task", 1), kinds)

    def test_tags_sync_round_trip(self):
        cloud = FakeCloud()
        engine = SyncEngine(self.store, client=cloud)
        engine.adopt_history_key(cloud.history_key)
        t = self._task(title="with tag", destination=models.DEST_ANYTIME)
        work = self.store.ensure_tag("Work")
        self.store.set_task_tags(t.uuid, [work.uuid])
        engine.sync_once()

        # the task envelope carries the tag uuid in ``tg``
        task_env = next(c[t.uuid] for c in cloud.commits if t.uuid in c)
        self.assertEqual(task_env["p"]["tg"], [work.uuid])
        # a Tag3 entity was written too
        self.assertTrue(
            any(
                env["e"] == serde.TAG_KIND
                for commit in cloud.commits
                for env in commit.values()
            )
        )

        # a fresh store pulls the tag + association back
        store2 = Store(tempfile.mktemp(suffix=".db"))
        eng2 = SyncEngine(store2, client=cloud)
        eng2.adopt_history_key(cloud.history_key)
        eng2.pull()
        pulled = store2.anytime()[0]
        self.assertEqual(pulled.tags, [work.uuid])
        self.assertEqual(store2.tag_map().get(work.uuid), "Work")
        store2.close()

    def test_move_task_into_project_clears_area(self):
        area = self.store.add_area(Area(uuid=config.new_id(), title="Work"))
        proj = self._task(title="Proj", type=models.TYPE_PROJECT, area=area.uuid)
        t = self._task(title="task")
        self.store.update_task(
            t.uuid, {"project": proj.uuid, "area": None, "destination": models.DEST_ANYTIME}
        )
        moved = self.store.get_task(t.uuid)
        self.assertEqual(moved.project, proj.uuid)
        self.assertIsNone(moved.area)
        self.assertEqual([x.title for x in self.store.project_tasks(proj.uuid)], ["task"])


if __name__ == "__main__":
    unittest.main()
