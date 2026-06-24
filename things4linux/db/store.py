"""SQLite data-access layer and the UI's view queries.

The store is the single source of truth for the UI. Every *local* mutation writes
the row, flags it ``dirty`` and appends an entry to ``change_queue`` for the sync
engine to push. Applying a *remote* change (from the server) never touches the
queue and never clobbers an un-pushed local edit.

A single connection is shared across the UI and engine threads
(``check_same_thread=False``) guarded by one re-entrant lock; writes are small and
infrequent, so coarse locking is plenty.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .. import config
from . import models
from .models import Area, Tag, Task

_SCHEMA = Path(__file__).with_name("schema.sql")

# Internal task fields that map 1:1 to columns in the ``task`` table.
_TASK_COLUMNS = (
    "title", "notes", "type", "status", "destination", "index", "today_index",
    "scheduled_date", "deadline", "completion_date", "creation_date",
    "modification_date", "trashed", "evening", "area", "project", "heading",
)
_AREA_COLUMNS = ("title", "index", "trashed")
_TAG_COLUMNS = ("title", "shortcut", "index")


def _quote(col: str) -> str:
    return f'"{col}"' if col == "index" else col


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or config.database_path())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA.read_text())
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sync_state -------------------------------------------------------------------
    def get_history_key(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT history_key FROM sync_state WHERE id = 1"
            ).fetchone()
            return row["history_key"] if row else None

    def set_history_key(self, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sync_state SET history_key = ? WHERE id = 1", (key,)
            )
            self._conn.commit()

    def get_head_index(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT head_index FROM sync_state WHERE id = 1"
            ).fetchone()
            return int(row["head_index"]) if row else 0

    def set_head_index(self, index: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sync_state SET head_index = ? WHERE id = 1", (index,)
            )
            self._conn.commit()

    # -- generic upsert ---------------------------------------------------------------
    def _upsert(self, table: str, uuid: str, fields: dict[str, Any], columns: Iterable[str]) -> None:
        cols = [c for c in columns if c in fields]
        exists = self._conn.execute(
            f"SELECT 1 FROM {table} WHERE uuid = ?", (uuid,)
        ).fetchone()
        if exists:
            if not cols:
                return
            assignments = ", ".join(f"{_quote(c)} = ?" for c in cols)
            params = [_coerce(fields[c]) for c in cols] + [uuid]
            self._conn.execute(
                f"UPDATE {table} SET {assignments} WHERE uuid = ?", params
            )
        else:
            all_cols = ["uuid"] + cols
            placeholders = ", ".join("?" for _ in all_cols)
            col_sql = ", ".join(_quote(c) for c in all_cols)
            params = [uuid] + [_coerce(fields[c]) for c in cols]
            self._conn.execute(
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})", params
            )

    # -- remote application (no dirty flag, no queue) ---------------------------------
    def apply_remote(self, kind: str, uuid: str, op: int, fields: dict[str, Any]) -> None:
        """Apply a decoded change received from the server."""
        with self._lock:
            if kind == "task":
                self._apply_remote_task(uuid, op, fields)
            elif kind == "area":
                self._upsert("area", uuid, fields, _AREA_COLUMNS)
            elif kind == "tag":
                self._upsert("tag", uuid, fields, _TAG_COLUMNS)
            elif kind == "checklist":
                self._apply_remote_checklist(uuid, fields)
            self._conn.commit()

    def _is_dirty(self, table: str, uuid: str) -> bool:
        if table != "task":
            return False
        row = self._conn.execute(
            "SELECT dirty FROM task WHERE uuid = ?", (uuid,)
        ).fetchone()
        return bool(row and row["dirty"])

    def _apply_remote_task(self, uuid: str, op: int, fields: dict[str, Any]) -> None:
        # Don't clobber an un-pushed local edit; our commit will reconcile it.
        if self._is_dirty("task", uuid):
            return
        if op == 2:  # explicit delete -> trash
            fields = {**fields, "trashed": True}
        tags = fields.pop("tags", None)
        self._upsert("task", uuid, fields, _TASK_COLUMNS)
        if tags is not None:
            self._set_tags(uuid, tags)

    def _apply_remote_checklist(self, uuid: str, fields: dict[str, Any]) -> None:
        cols = ("task", "title", "status", "index", "completion_date")
        self._upsert("checklist_item", uuid, fields, cols)

    def _set_tags(self, task_uuid: str, tags: list[str]) -> None:
        self._conn.execute("DELETE FROM task_tag WHERE task_uuid = ?", (task_uuid,))
        self._conn.executemany(
            "INSERT OR IGNORE INTO task_tag (task_uuid, tag_uuid) VALUES (?, ?)",
            [(task_uuid, t) for t in tags],
        )

    # -- local mutations (set dirty + enqueue) ----------------------------------------
    def add_task(self, task: Task) -> Task:
        now = time.time()
        if task.creation_date is None:
            task.creation_date = now
        task.modification_date = now
        fields = _task_to_fields(task)
        with self._lock:
            self._upsert("task", task.uuid, fields, _TASK_COLUMNS)
            self._conn.execute("UPDATE task SET dirty = 1 WHERE uuid = ?", (task.uuid,))
            if task.tags:
                self._set_tags(task.uuid, task.tags)
            self._enqueue(task.uuid, "task", 0, fields)
            self._conn.commit()
        return task

    def update_task(self, uuid: str, changes: dict[str, Any]) -> None:
        """Apply a local edit. ``changes`` uses internal field names."""
        changes = dict(changes)
        changes["modification_date"] = time.time()
        with self._lock:
            self._upsert("task", uuid, changes, _TASK_COLUMNS)
            self._conn.execute("UPDATE task SET dirty = 1 WHERE uuid = ?", (uuid,))
            self._enqueue(uuid, "task", 1, changes)
            self._conn.commit()

    def complete_task(self, uuid: str) -> None:
        self.update_task(
            uuid,
            {"status": models.STATUS_COMPLETED, "completion_date": int(time.time())},
        )

    def reopen_task(self, uuid: str) -> None:
        self.update_task(uuid, {"status": models.STATUS_TODO, "completion_date": None})

    def trash_task(self, uuid: str) -> None:
        self.update_task(uuid, {"trashed": True})

    def add_area(self, area: Area) -> Area:
        fields = {"title": area.title, "index": area.index, "trashed": area.trashed}
        with self._lock:
            self._upsert("area", area.uuid, fields, _AREA_COLUMNS)
            self._enqueue(area.uuid, "area", 0, fields)
            self._conn.commit()
        return area

    def _enqueue(self, uuid: str, kind: str, op: int, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO change_queue (uuid, kind, op, fields, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (uuid, kind, op, json.dumps(_jsonable(fields)), time.time()),
        )

    # -- change queue (used by the engine) --------------------------------------------
    def pending_changes(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT seq, uuid, kind, op, fields FROM change_queue ORDER BY seq"
            ).fetchall()

    def clear_changes(self, seqs: Iterable[int], uuids: Iterable[str]) -> None:
        with self._lock:
            seqs = list(seqs)
            if seqs:
                marks = ",".join("?" for _ in seqs)
                self._conn.execute(
                    f"DELETE FROM change_queue WHERE seq IN ({marks})", seqs
                )
            for uuid in set(uuids):
                # Only clear dirty if no newer change was queued meanwhile.
                still = self._conn.execute(
                    "SELECT 1 FROM change_queue WHERE uuid = ? LIMIT 1", (uuid,)
                ).fetchone()
                if not still:
                    self._conn.execute(
                        "UPDATE task SET dirty = 0 WHERE uuid = ?", (uuid,)
                    )
            self._conn.commit()

    # -- view queries -----------------------------------------------------------------
    def _tasks(self, where: str, params: tuple = ()) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM task WHERE {where}", params
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    def inbox(self) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND status = ? AND destination = ? AND type = ? "
            "AND project IS NULL AND area IS NULL ORDER BY \"index\"",
            (models.STATUS_TODO, models.DEST_INBOX, models.TYPE_TASK),
        )

    def today(self) -> list[Task]:
        end = _end_of_today()
        return self._tasks(
            "trashed = 0 AND status = ? AND scheduled_date IS NOT NULL "
            "AND scheduled_date <= ? ORDER BY evening, today_index, \"index\"",
            (models.STATUS_TODO, end),
        )

    def upcoming(self) -> list[Task]:
        end = _end_of_today()
        return self._tasks(
            "trashed = 0 AND status = ? AND scheduled_date IS NOT NULL "
            "AND scheduled_date > ? ORDER BY scheduled_date",
            (models.STATUS_TODO, end),
        )

    def anytime(self) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND status = ? AND destination = ? AND scheduled_date IS NULL "
            "ORDER BY \"index\"",
            (models.STATUS_TODO, models.DEST_ANYTIME),
        )

    def someday(self) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND status = ? AND destination = ? ORDER BY \"index\"",
            (models.STATUS_TODO, models.DEST_SOMEDAY),
        )

    def logbook(self) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND status IN (?, ?) ORDER BY completion_date DESC",
            (models.STATUS_COMPLETED, models.STATUS_CANCELLED),
        )

    def trash(self) -> list[Task]:
        return self._tasks("trashed = 1 ORDER BY modification_date DESC")

    def project_tasks(self, project_uuid: str) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND project = ? AND status = ? ORDER BY \"index\"",
            (project_uuid, models.STATUS_TODO),
        )

    def area_tasks(self, area_uuid: str) -> list[Task]:
        return self._tasks(
            "trashed = 0 AND area = ? AND project IS NULL AND status = ? "
            "ORDER BY \"index\"",
            (area_uuid, models.STATUS_TODO),
        )

    def areas(self) -> list[Area]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM area WHERE trashed = 0 ORDER BY \"index\""
            ).fetchall()
        return [Area(uuid=r["uuid"], title=r["title"], index=r["index"]) for r in rows]

    def projects(self, area_uuid: str | None = None) -> list[Task]:
        if area_uuid is None:
            return self._tasks(
                "trashed = 0 AND type = ? AND status = ? ORDER BY \"index\"",
                (models.TYPE_PROJECT, models.STATUS_TODO),
            )
        return self._tasks(
            "trashed = 0 AND type = ? AND area = ? AND status = ? ORDER BY \"index\"",
            (models.TYPE_PROJECT, area_uuid, models.STATUS_TODO),
        )

    def tags(self) -> list[Tag]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tag ORDER BY \"index\""
            ).fetchall()
        return [
            Tag(uuid=r["uuid"], title=r["title"], shortcut=r["shortcut"], index=r["index"])
            for r in rows
        ]

    def get_task(self, uuid: str) -> Task | None:
        rows = self._tasks("uuid = ?", (uuid,))
        return rows[0] if rows else None

    def counts(self) -> dict[str, int]:
        """Badge counts for the sidebar built-in views."""
        return {
            "inbox": len(self.inbox()),
            "today": len(self.today()),
        }


# --- module helpers ------------------------------------------------------------------
def _coerce(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _jsonable(fields: dict[str, Any]) -> dict[str, Any]:
    return fields


def _task_to_fields(task: Task) -> dict[str, Any]:
    return {
        "title": task.title,
        "notes": task.notes,
        "type": task.type,
        "status": task.status,
        "destination": task.destination,
        "index": task.index,
        "today_index": task.today_index,
        "scheduled_date": task.scheduled_date,
        "deadline": task.deadline,
        "completion_date": task.completion_date,
        "creation_date": task.creation_date,
        "modification_date": task.modification_date,
        "trashed": task.trashed,
        "evening": task.evening,
        "area": task.area,
        "project": task.project,
        "heading": task.heading,
    }


def _row_to_task(r: sqlite3.Row) -> Task:
    return Task(
        uuid=r["uuid"],
        title=r["title"],
        notes=r["notes"],
        type=r["type"],
        status=r["status"],
        destination=r["destination"],
        index=r["index"],
        today_index=r["today_index"],
        scheduled_date=r["scheduled_date"],
        deadline=r["deadline"],
        completion_date=r["completion_date"],
        creation_date=r["creation_date"],
        modification_date=r["modification_date"],
        trashed=bool(r["trashed"]),
        evening=bool(r["evening"]),
        area=r["area"],
        project=r["project"],
        heading=r["heading"],
    )


def _end_of_today() -> int:
    """Epoch seconds at the end of the local day (for Today/Upcoming split)."""
    lt = time.localtime()
    midnight = time.mktime(
        (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)
    )
    return int(midnight + 86400 - 1)
