import time
import unittest

from things4linux import views
from things4linux.db.models import Task


def _t(uuid, evening=False, scheduled=None):
    return Task(uuid=uuid, evening=evening, scheduled_date=scheduled)


class ViewsTest(unittest.TestCase):
    def test_split_today(self):
        tasks = [_t("a"), _t("b", evening=True), _t("c")]
        day, evening = views.split_today(tasks)
        self.assertEqual([t.uuid for t in day], ["a", "c"])
        self.assertEqual([t.uuid for t in evening], ["b"])

    def test_upcoming_labels(self):
        # fix "now" to noon so day boundaries are unambiguous
        now = time.mktime((2026, 6, 24, 12, 0, 0, 0, 0, -1))
        day = 86400

        def at(d):  # start-of-day epoch d days from today
            return int(views._start_of_day(now) + d * day)

        self.assertEqual(views.upcoming_label(at(1), now), "Tomorrow")
        # 3 days out -> weekday name
        self.assertEqual(
            views.upcoming_label(at(3), now),
            time.strftime("%A", time.localtime(at(3))),
        )
        # far out -> abbreviated date
        self.assertEqual(
            views.upcoming_label(at(40), now),
            time.strftime("%a %-d %b", time.localtime(at(40))),
        )

    def test_group_upcoming_groups_by_day(self):
        now = time.mktime((2026, 6, 24, 12, 0, 0, 0, 0, -1))
        d = int(views._start_of_day(now))
        tasks = [
            _t("a", scheduled=d + 1 * 86400 + 100),
            _t("b", scheduled=d + 1 * 86400 + 500),  # same day as a
            _t("c", scheduled=d + 3 * 86400),
        ]
        groups = views.group_upcoming(tasks, now)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][0], "Tomorrow")
        self.assertEqual([t.uuid for t in groups[0][1]], ["a", "b"])
        self.assertEqual([t.uuid for t in groups[1][1]], ["c"])


if __name__ == "__main__":
    unittest.main()
