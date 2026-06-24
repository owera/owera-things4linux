"""Pure view-grouping helpers (no GTK), so they can be unit-tested directly.

These shape the ordered task lists from the store into the sectioned layout
Things shows: a "This Evening" split in Today, and day-by-day groups in Upcoming.
"""

from __future__ import annotations

import time
from typing import Iterable

from .db.models import Task


def normalize_query(query: str) -> list[str]:
    """Lower-cased search terms; every term must match (AND semantics)."""
    return [w for w in query.lower().split() if w]


def match_task(task: Task, terms: list[str]) -> bool:
    haystack = f"{task.title}\n{task.notes}".lower()
    return all(term in haystack for term in terms)


def search_rank(task: Task, terms: list[str]):
    """Sort key for search results: title matches first, open before done."""
    title = task.title.lower()
    in_title = all(term in title for term in terms)
    return (0 if in_title else 1, 0 if task.status == 0 else 1, title)


def split_today(tasks: Iterable[Task]) -> tuple[list[Task], list[Task]]:
    """Return (daytime, evening) for the Today view."""
    day, evening = [], []
    for t in tasks:
        (evening if t.evening else day).append(t)
    return day, evening


def _ymd(epoch: int) -> tuple[int, int, int]:
    lt = time.localtime(epoch)
    return (lt.tm_year, lt.tm_mon, lt.tm_mday)


def upcoming_label(epoch: int, now: float | None = None) -> str:
    """Human label for an Upcoming date header, relative to ``now``."""
    now = time.time() if now is None else now
    today_mid = _start_of_day(now)
    target_mid = _start_of_day(epoch)
    days = round((target_mid - today_mid) / 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days < 7:
        return time.strftime("%A", time.localtime(epoch))  # weekday name
    return time.strftime("%a %-d %b", time.localtime(epoch))


def group_upcoming(
    tasks: Iterable[Task], now: float | None = None
) -> list[tuple[str, list[Task]]]:
    """Group date-ordered tasks into [(header, tasks), …] by calendar day."""
    groups: list[tuple[str, list[Task]]] = []
    cur_key: tuple[int, int, int] | None = None
    for t in tasks:
        if t.scheduled_date is None:
            continue
        key = _ymd(t.scheduled_date)
        if key != cur_key:
            groups.append((upcoming_label(t.scheduled_date, now), []))
            cur_key = key
        groups[-1][1].append(t)
    return groups


def _start_of_day(epoch: float) -> float:
    lt = time.localtime(epoch)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
