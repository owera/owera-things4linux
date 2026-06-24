import os
import tempfile
import unittest

from things4linux import config
from things4linux.db import models
from things4linux.db.models import Task
from things4linux.db.store import Store
from things4linux.sync import serde
from things4linux.sync.engine import SyncEngine

from .fake_cloud import FakeCloud


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.store = Store(self.path)
        self.cloud = FakeCloud()
        self.engine = SyncEngine(self.store, client=self.cloud)
        self.engine.adopt_history_key(self.cloud.history_key)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_initial_pull_populates_store(self):
        self.cloud.server_push(
            config.new_id(), serde.TASK_KIND, 0,
            serde.encode_task({"title": "from server", "destination": 0}, partial=False),
        )
        applied = self.engine.pull()
        self.assertTrue(applied)
        self.assertEqual([t.title for t in self.store.inbox()], ["from server"])
        self.assertEqual(self.store.get_head_index(), 1)

    def test_local_create_is_pushed(self):
        task = Task(uuid=config.new_id(), title="local")
        self.store.add_task(task)
        pushed = self.engine.push()
        self.assertTrue(pushed)
        # server received exactly one envelope, a create for our uuid
        self.assertEqual(len(self.cloud.history), 1)
        env = self.cloud.history[0][task.uuid]
        self.assertEqual(env["t"], int(serde.Op.NEW))
        self.assertEqual(env["e"], serde.TASK_KIND)
        self.assertEqual(env["p"]["tt"], "local")
        # head advanced, dirty cleared
        self.assertEqual(self.store.get_head_index(), 1)
        self.assertEqual(self.store.pending_changes(), [])

    def test_create_then_edit_coalesce_to_single_create(self):
        task = Task(uuid=config.new_id(), title="first")
        self.store.add_task(task)
        self.store.update_task(task.uuid, {"title": "second"})
        self.assertEqual(len(self.store.pending_changes()), 2)
        self.engine.push()
        self.assertEqual(len(self.cloud.history), 1)  # one merged envelope
        env = self.cloud.history[0][task.uuid]
        self.assertEqual(env["t"], int(serde.Op.NEW))
        self.assertEqual(env["p"]["tt"], "second")

    def test_push_retries_after_stale_ancestor(self):
        # Another device commits first, so our ancestor index is stale.
        self.cloud.server_push(
            config.new_id(), serde.TASK_KIND, 0,
            serde.encode_task({"title": "other device"}, partial=False),
        )
        task = Task(uuid=config.new_id(), title="mine")
        self.store.add_task(task)
        # head_index is still 0 locally; commit should fail then retry after pull
        self.engine.push()
        titles = sorted(t.title for t in self.store.inbox())
        self.assertEqual(titles, ["mine", "other device"])
        self.assertEqual(len(self.cloud.history), 2)

    def test_sync_once_roundtrip(self):
        task = Task(uuid=config.new_id(), title="hello", destination=models.DEST_ANYTIME)
        self.store.add_task(task)
        self.engine.sync_once()
        # appears on server, and a fresh store can pull it back
        self.assertEqual(len(self.cloud.history), 1)
        store2 = Store(tempfile.mktemp(suffix=".db"))
        eng2 = SyncEngine(store2, client=self.cloud)
        eng2.adopt_history_key(self.cloud.history_key)
        eng2.pull()
        self.assertEqual([t.title for t in store2.anytime()], ["hello"])
        store2.close()


if __name__ == "__main__":
    unittest.main()
