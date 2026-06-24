"""Translation between Things Cloud payloads and our internal model dicts.

Things Cloud transmits an append-only history of *items*. Each item is a small
envelope::

    { "<uuid>": { "t": <op>, "e": "<EntityKind>", "p": { <payload> } } }

where the payload ``p`` uses cryptic two-letter keys (``tt`` = title, ``ss`` =
status, ...). This module is the single source of truth for that mapping. It is
deliberately free of any GTK / DB imports so it can be unit-tested in isolation.

Internal model dicts use the verbose field names declared in ``db/models.py``.
Decoders return only the fields actually present in the payload (so callers can
distinguish "absent" from "explicitly null"); encoders can emit either a full
payload (for creates) or a partial one (for edits — only changed fields).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

# --- enumerations --------------------------------------------------------------------


class Op(IntEnum):
    """Operation kind carried in the item envelope's ``t`` field."""

    NEW = 0
    EDIT = 1
    DELETE = 2  # rarely used; deletes are usually edits that set ``trashed``.


class ItemType(IntEnum):
    """Payload ``tp`` field — what kind of TMTask this is."""

    TASK = 0
    PROJECT = 1
    HEADING = 2


class Status(IntEnum):
    """Payload ``ss`` field."""

    TODO = 0
    CANCELLED = 2
    COMPLETED = 3


class Destination(IntEnum):
    """Payload ``st`` field — which top-level bucket the item belongs to."""

    INBOX = 0
    ANYTIME = 1
    SOMEDAY = 2


# Entity kinds (envelope ``e`` field). The server has historically used several
# generations; we read all known variants but always *write* the newest.
TASK_KINDS = {"Task6", "Task3", "Task"}
AREA_KINDS = {"Area2", "Area"}
TAG_KINDS = {"Tag3", "Tag"}
CHECKLIST_KINDS = {"ChecklistItem3", "ChecklistItem"}
TASK_KIND = "Task6"
AREA_KIND = "Area2"
TAG_KIND = "Tag3"
CHECKLIST_KIND = "ChecklistItem3"


# --- task field mapping --------------------------------------------------------------
# two-letter payload key  <->  internal model field name (for plain scalar fields).
TASK_FIELDS: dict[str, str] = {
    "ix": "index",
    "tt": "title",
    "ss": "status",
    "st": "destination",
    "tp": "type",
    "cd": "creation_date",
    "md": "modification_date",
    "sr": "scheduled_date",
    "sp": "completion_date",
    "dd": "deadline",
    "tr": "trashed",
    "ti": "today_index",
}
_TASK_FIELDS_INV = {v: k for k, v in TASK_FIELDS.items()}

# List-of-uuid relations are stored singular internally (Things only ever puts one
# parent in each list in practice), so they need bespoke handling.
_TASK_LIST_RELATIONS = {"pr": "project", "ar": "area", "agr": "heading"}
_TASK_LIST_RELATIONS_INV = {v: k for k, v in _TASK_LIST_RELATIONS.items()}


def _decode_note(value: Any) -> str:
    """Things notes are ``{"_t": "tx", "v": <text>, "ch": .., "t": ..}``."""
    if isinstance(value, dict):
        return value.get("v") or ""
    if isinstance(value, str):
        return value
    return ""


def _encode_note(text: str) -> dict[str, Any]:
    return {"_t": "tx", "v": text or "", "ch": 0, "t": 1}


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


def decode_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a Things task payload into a partial internal model dict."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in TASK_FIELDS:
            field = TASK_FIELDS[key]
            if field in ("creation_date", "modification_date") and value is not None:
                out[field] = float(value)
            elif field == "trashed":
                out[field] = bool(value)
            else:
                out[field] = value
        elif key in _TASK_LIST_RELATIONS:
            out[_TASK_LIST_RELATIONS[key]] = _first(value)
        elif key == "nt":
            out["notes"] = _decode_note(value)
        elif key == "sb":
            out["evening"] = bool(value)
        elif key == "tg":
            out["tags"] = list(value) if isinstance(value, list) else []
    return out


def encode_task(model: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """Convert an internal task model dict into a Things payload.

    ``partial=False`` emits a full create payload (with sensible defaults for the
    structural fields the server expects); ``partial=True`` emits only the keys
    present in ``model`` (used for edits — never send unchanged fields).
    """
    p: dict[str, Any] = {}
    for field, value in model.items():
        if field in _TASK_FIELDS_INV:
            p[_TASK_FIELDS_INV[field]] = value
        elif field in _TASK_LIST_RELATIONS_INV:
            p[_TASK_LIST_RELATIONS_INV[field]] = [value] if value else []
        elif field == "notes":
            p["nt"] = _encode_note(value)
        elif field == "evening":
            p["sb"] = 1 if value else 0
        elif field == "tags":
            p["tg"] = list(value) if value else []

    if not partial:
        # Structural defaults the macOS client always sends on create.
        p.setdefault("tt", "")
        p.setdefault("ss", int(Status.TODO))
        p.setdefault("st", int(Destination.INBOX))
        p.setdefault("tp", int(ItemType.TASK))
        p.setdefault("ix", 0)
        p.setdefault("tr", False)
        p.setdefault("pr", [])
        p.setdefault("ar", [])
        p.setdefault("agr", [])
        p.setdefault("tg", [])
        p.setdefault("sb", 0)
        p.setdefault("nt", _encode_note(""))
    return p


# --- area / tag mapping --------------------------------------------------------------

AREA_FIELDS = {"ix": "index", "tt": "title", "tr": "trashed"}
_AREA_FIELDS_INV = {v: k for k, v in AREA_FIELDS.items()}
TAG_FIELDS = {"ix": "index", "tt": "title", "sh": "shortcut"}
_TAG_FIELDS_INV = {v: k for k, v in TAG_FIELDS.items()}


def decode_simple(payload: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in mapping:
            field = mapping[key]
            out[field] = bool(value) if field == "trashed" else value
    return out


def encode_simple(model: dict[str, Any], inv: dict[str, str]) -> dict[str, Any]:
    return {inv[f]: v for f, v in model.items() if f in inv}


# --- envelope helpers ----------------------------------------------------------------


def classify(entity: str) -> str:
    """Return a coarse category for an entity kind: task/area/tag/checklist/other."""
    if entity in TASK_KINDS:
        return "task"
    if entity in AREA_KINDS:
        return "area"
    if entity in TAG_KINDS:
        return "tag"
    if entity in CHECKLIST_KINDS:
        return "checklist"
    return "other"


def decode_item(entity: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Decode a payload according to its entity kind."""
    kind = classify(entity)
    if kind == "task":
        return decode_task(payload)
    if kind == "area":
        return decode_simple(payload, AREA_FIELDS)
    if kind == "tag":
        return decode_simple(payload, TAG_FIELDS)
    if kind == "checklist":
        return decode_simple(payload, {**TASK_FIELDS, "ts": "task"})
    return {}


def make_envelope(op: Op, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the ``{t, e, p}`` envelope written to ``/commit``."""
    return {"t": int(op), "e": entity, "p": payload}
