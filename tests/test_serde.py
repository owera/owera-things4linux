import unittest

from things4linux.sync import serde


class SerdeTest(unittest.TestCase):
    def test_task_edit_roundtrip(self):
        model = {
            "title": "Buy milk",
            "notes": "2%",
            "status": serde.Status.TODO,
            "destination": serde.Destination.ANYTIME,
            "scheduled_date": 1719187200,
            "evening": True,
            "project": "PROJ123",
            "modification_date": 1719187234.5,
        }
        payload = serde.encode_task(model, partial=True)
        self.assertEqual(payload["tt"], "Buy milk")
        self.assertEqual(payload["nt"]["v"], "2%")
        self.assertEqual(payload["sb"], 1)
        self.assertEqual(payload["pr"], ["PROJ123"])

        back = serde.decode_task(payload)
        self.assertEqual(back["title"], "Buy milk")
        self.assertTrue(back["evening"])
        self.assertEqual(back["project"], "PROJ123")
        self.assertEqual(back["notes"], "2%")

    def test_full_create_is_complete(self):
        # A create must be a COMPLETE TodoApiObject; the server orphans a commit
        # whose NewBody is missing fields. Pin the full required key set.
        payload = serde.encode_task({"title": "X"}, partial=False)
        required = {
            "ix", "tt", "ss", "st", "cd", "md", "sr", "tir", "sp", "dd", "tr",
            "icp", "pr", "ar", "sb", "tg", "tp", "dds", "rt", "rmd", "dl", "do",
            "lai", "agr", "lt", "icc", "ti", "ato", "icsd", "rp", "acrd", "rr",
            "nt", "xx",
        }
        self.assertEqual(required - set(payload), set(), "missing create fields")
        self.assertEqual(payload["ss"], int(serde.Status.TODO))
        self.assertIsInstance(payload["cd"], float)
        self.assertEqual(payload["xx"], {"sn": {}, "_t": "oo"})

    def test_classify_handles_entity_generations(self):
        for ent in ("Task", "Task2", "Task6"):
            self.assertEqual(serde.classify(ent), "task")
        for ent in ("Tag", "Tag2", "Tag3"):
            self.assertEqual(serde.classify(ent), "tag")
        for ent in ("Area", "Area2"):
            self.assertEqual(serde.classify(ent), "area")
        self.assertEqual(serde.classify("Settings2"), "other")
        self.assertEqual(serde.classify("Contact"), "other")

    def test_edit_sends_only_present_fields(self):
        payload = serde.encode_task({"status": serde.Status.COMPLETED}, partial=True)
        self.assertEqual(set(payload), {"ss"})

    def test_clearing_a_relation_sends_empty_list(self):
        payload = serde.encode_task({"project": None}, partial=True)
        self.assertEqual(payload["pr"], [])

    def test_classify_and_decode_area(self):
        self.assertEqual(serde.classify("Area2"), "area")
        self.assertEqual(serde.classify("Task6"), "task")
        decoded = serde.decode_item("Area2", {"tt": "Work", "ix": 3})
        self.assertEqual(decoded, {"title": "Work", "index": 3})

    def test_envelope(self):
        env = serde.make_envelope(serde.Op.NEW, serde.TASK_KIND, {"tt": "hi"})
        self.assertEqual(env, {"t": 0, "e": "Task6", "p": {"tt": "hi"}})


if __name__ == "__main__":
    unittest.main()
