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


class SearchMatchTest(unittest.TestCase):
    def test_normalize_and_match_all_terms(self):
        terms = views.normalize_query("  Buy   Milk ")
        self.assertEqual(terms, ["buy", "milk"])
        t = Task(uuid="x", title="Buy oat milk", notes="from the shop")
        self.assertTrue(views.match_task(t, terms))
        self.assertFalse(views.match_task(t, views.normalize_query("buy bread")))

    def test_match_searches_notes(self):
        t = Task(uuid="x", title="Call", notes="ring the dentist")
        self.assertTrue(views.match_task(t, views.normalize_query("dentist")))

    def test_rank_prefers_title_then_open(self):
        title_hit = Task(uuid="a", title="dentist appt")
        notes_hit = Task(uuid="b", title="call", notes="dentist")
        done_title = Task(uuid="c", title="dentist done", status=3)
        terms = views.normalize_query("dentist")
        ranked = sorted([notes_hit, done_title, title_hit],
                        key=lambda t: views.search_rank(t, terms))
        self.assertEqual([t.uuid for t in ranked], ["a", "c", "b"])


if __name__ == "__main__":
    unittest.main()
