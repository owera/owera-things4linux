"""Plain dataclasses mirroring Things' core entities.

Field names are the verbose internal names used throughout the app; the mapping
to Things Cloud's two-letter wire keys lives in ``sync/serde.py``. Dates are
stored as Unix epoch seconds (``float`` for creation/modification which Things
sends with sub-second precision, ``int`` for the date-only "when"/deadline).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# status values (match serde.Status)
STATUS_TODO = 0
STATUS_CANCELLED = 2
STATUS_COMPLETED = 3

# destination values (match serde.Destination)
DEST_INBOX = 0
DEST_ANYTIME = 1
DEST_SOMEDAY = 2

# type values (match serde.ItemType)
TYPE_TASK = 0
TYPE_PROJECT = 1
TYPE_HEADING = 2


@dataclass
class Task:
    uuid: str
    title: str = ""
    notes: str = ""
    type: int = TYPE_TASK
    status: int = STATUS_TODO
    destination: int = DEST_INBOX
    index: int = 0
    today_index: int = 0
    scheduled_date: int | None = None  # the "when" date
    deadline: int | None = None
    completion_date: int | None = None
    creation_date: float | None = None
    modification_date: float | None = None
    trashed: bool = False
    evening: bool = False
    area: str | None = None
    project: str | None = None
    heading: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class Area:
    uuid: str
    title: str = ""
    index: int = 0
    trashed: bool = False


@dataclass
class Tag:
    uuid: str
    title: str = ""
    shortcut: str | None = None
    index: int = 0


@dataclass
class ChecklistItem:
    uuid: str
    task: str | None = None
    title: str = ""
    status: int = STATUS_TODO
    index: int = 0
    completion_date: int | None = None
