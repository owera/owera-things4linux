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

    def test_write_entity_is_learned_from_history(self):
        # Server history uses the older "Task2" generation.
        self.cloud.server_push(
            config.new_id(), "Task2", 0,
            serde.encode_task({"title": "legacy"}, partial=False),
        )
        self.engine.pull()
        self.assertEqual(self.store.write_entity("task", serde.TASK_KIND), "Task2")
        # A local create should now be written as Task2, matching the account.
        t = Task(uuid=config.new_id(), title="mine")
        self.store.add_task(t)
        self.engine.push()
        env = self.cloud.history[-1][t.uuid]
        self.assertEqual(env["e"], "Task2")

    def test_empty_trash_pushes_deletes(self):
        # two trashed tasks (applied as remote so they aren't dirty)
        u1, u2 = config.new_id(), config.new_id()
        self.store.apply_remote("task", u1, 0, {"title": "a", "trashed": True})
        self.store.apply_remote("task", u2, 0, {"title": "b", "trashed": True})
        n = self.store.empty_trash()
        self.assertEqual(n, 2)
        self.assertEqual(self.store.trash(), [])  # gone locally
        self.engine.push()
        # both pushed as op=2 deletes with empty payloads
        last = self.cloud.history[-2:]
        for entry in last:
            (env,) = entry.values()
            self.assertEqual(env["t"], int(serde.Op.DELETE))
            self.assertEqual(env["p"], {})

    def test_create_then_delete_coalesces_to_nothing(self):
        t = Task(uuid=config.new_id(), title="ephemeral")
        self.store.add_task(t)          # op 0 queued
        self.store.empty_trash()        # nothing trashed yet -> no-op
        self.store.trash_task(t.uuid)   # op 1 (trashed=True) queued
        self.store.empty_trash()        # now trashed -> op 2 queued + row removed
        before = len(self.cloud.history)
        self.engine.push()
        # created+deleted before any sync: server sees nothing, queue still drained
        self.assertEqual(len(self.cloud.history), before)
        self.assertEqual(self.store.pending_changes(), [])

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
