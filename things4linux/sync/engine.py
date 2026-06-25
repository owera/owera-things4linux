"""Background synchronisation engine.

Runs on its own daemon thread and reconciles the local :class:`Store` with Things
Cloud:

* **pull** — fetch new history items from ``head_index`` and apply them locally,
  advancing ``head_index``;
* **push** — drain the local ``change_queue``, coalesce per item, and ``/commit``
  the batch at ``ancestor-index = head_index``.

The engine owns no GTK state. It reports progress through two callbacks
(``on_changed`` / ``on_status``) which the UI wraps with ``GLib.idle_add`` so they
land on the main loop.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .. import config
from ..db import models
from ..db.store import Store
from . import serde
from .protocol import AuthError, ThingsClient, ThingsCloudError

StatusCb = Callable[[str, str], None]
ChangedCb = Callable[[], None]

# entity kind written for each internal category
_WRITE_ENTITY = {
    "task": serde.TASK_KIND,
    "area": serde.AREA_KIND,
    "tag": serde.TAG_KIND,
    "checklist": serde.CHECKLIST_KIND,
}


class SyncEngine:
    def __init__(
        self,
        store: Store,
        *,
        on_changed: ChangedCb | None = None,
        on_status: StatusCb | None = None,
        client: ThingsClient | None = None,
    ):
        self.store = store
        self._client = client or ThingsClient()
        self._on_changed = on_changed or (lambda: None)
        self._on_status = on_status or (lambda state, detail: None)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._history_key = store.get_history_key()
        # most-recent entity kind seen per family, learned while pulling
        self._latest_entity: dict[str, str] = {}

    # -- setup ------------------------------------------------------------------------
    def configure(self, email: str, password: str) -> str:
        """Log in, persist the history key, and return it. Raises on failure."""
        account = self._client.login(email, password)
        self._history_key = account.history_key
        self.store.set_history_key(account.history_key)
        return account.history_key

    @property
    def configured(self) -> bool:
        return bool(self._history_key)

    def set_callbacks(self, on_changed: ChangedCb, on_status: StatusCb) -> None:
        self._on_changed = on_changed
        self._on_status = on_status

    def adopt_history_key(self, key: str) -> None:
        """Use a history key obtained elsewhere (e.g. saved credentials)."""
        self._history_key = key
        self.store.set_history_key(key)

    # -- thread control ---------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def trigger(self) -> None:
        """Ask the engine to sync now (e.g. after a local edit)."""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
                self._on_status("online", "")
            except AuthError as exc:
                self._on_status("auth-error", str(exc))
            except ThingsCloudError as exc:
                self._on_status("offline", str(exc))
            except Exception as exc:  # never kill the thread
                self._on_status("error", repr(exc))
            self._wake.wait(timeout=config.SYNC_POLL_INTERVAL)
            self._wake.clear()

    # -- one cycle --------------------------------------------------------------------
    def sync_once(self) -> None:
        if not self._history_key:
            return
        applied = self.pull()
        pushed = self.push()
        if applied or pushed:
            self._on_changed()

    # -- pull -------------------------------------------------------------------------
    def pull(self) -> bool:
        """Pull and apply remote items until caught up. Returns True if any applied.

        The history is paged (≤2500 items per response); we advance the cursor by
        the number of items consumed until it reaches the head, persisting it each
        page so an interrupted sync resumes correctly.
        """
        assert self._history_key
        self._maybe_resync()
        applied = False
        while True:
            cursor = self.store.get_head_index()
            sl = self._client.pull(self._history_key, cursor)
            for entry in sl.items:
                self._apply_entry(entry)
                applied = True
            advanced = cursor + len(sl.items)
            self.store.set_head_index(advanced)
            if not sl.items or advanced >= sl.head_index:
                # Pin to the authoritative head (the commit ancestor-index).
                if sl.head_index > advanced:
                    self.store.set_head_index(sl.head_index)
                break
        if applied:
            self._persist_learned_entities()
        return applied

    def _maybe_resync(self) -> None:
        """One-time full re-sync for installs created before paginated pull.

        Only wipes a store that was *already* synced under the old (single-page)
        code — detected by a non-zero head. A fresh store (head 0) just records the
        flag and does its first full paged pull normally, preserving any un-pushed
        local changes.
        """
        if self.store.get_meta("sync_paginated") == "1":
            return
        if self.store.get_head_index() > 0:
            self.store.reset_for_full_resync()
        self.store.set_meta("sync_paginated", "1")

    def _apply_entry(self, entry: dict[str, Any]) -> None:
        for uuid, env in entry.items():
            entity = env.get("e", "")
            kind = serde.classify(entity)
            if kind == "other":
                continue
            # processed in history order, so the last seen is the most recent.
            self._latest_entity[kind] = entity
            decoded = serde.decode_item(entity, env.get("p", {}))
            self.store.apply_remote(kind, uuid, int(env.get("t", 1)), decoded)

    def _persist_learned_entities(self) -> None:
        for family, entity in self._latest_entity.items():
            self.store.set_meta(f"entity_{family}", entity)

    # -- push -------------------------------------------------------------------------
    def push(self) -> bool:
        """Commit queued local changes. Returns True if anything was pushed."""
        assert self._history_key
        pending = self.store.pending_changes()
        if not pending:
            return False

        merged, seqs, uuids = _coalesce(pending)
        body = {uuid: self._encode(item) for uuid, item in merged.items()}

        head = self.store.get_head_index()
        try:
            new_head = self._client.commit(self._history_key, head, body)
        except ThingsCloudError:
            # Likely a stale ancestor index: pull to catch up, then retry once.
            self.pull()
            head = self.store.get_head_index()
            new_head = self._client.commit(self._history_key, head, body)

        self.store.set_head_index(new_head)
        self.store.clear_changes(seqs, uuids)
        return True

    def _encode(self, item: dict[str, Any]) -> dict[str, Any]:
        kind = item["kind"]
        op = item["op"]
        fields = item["fields"]
        default = _WRITE_ENTITY.get(kind, serde.TASK_KIND)
        entity = self.store.write_entity(kind, default)
        if op == int(serde.Op.DELETE):
            payload: dict[str, Any] = {}  # permanent delete carries an empty payload
        elif kind == "task":
            payload = serde.encode_task(fields, partial=(op != 0))
        elif kind == "area":
            payload = serde.encode_simple(fields, serde._AREA_FIELDS_INV)
        elif kind == "tag":
            payload = serde.encode_simple(fields, serde._TAG_FIELDS_INV)
        else:
            payload = fields
        return serde.make_envelope(serde.Op(op), entity, payload)


def _coalesce(pending: list) -> tuple[dict[str, dict], list[int], list[str]]:
    """Collapse the queued changes for each uuid into at most one envelope.

    Rules, given the set of ops queued for a uuid:
    * ``NEW`` + ``DELETE`` (created and deleted before any sync) -> emit nothing;
    * any ``DELETE`` -> a single ``DELETE`` (empty payload);
    * any ``NEW`` -> a single ``NEW`` with all fields merged (a create);
    * otherwise -> a single ``EDIT`` (last value wins per field).

    ``seqs``/``uuids`` cover *every* drained row so the queue is fully cleared,
    even for uuids whose net effect is a no-op.
    """
    import json

    acc: dict[str, dict] = {}
    seqs: list[int] = []
    uuids: list[str] = []
    for row in pending:
        seqs.append(row["seq"])
        uuid = row["uuid"]
        uuids.append(uuid)
        entry = acc.setdefault(uuid, {"kind": row["kind"], "ops": set(), "fields": {}})
        entry["ops"].add(int(row["op"]))
        entry["fields"].update(json.loads(row["fields"]))

    merged: dict[str, dict] = {}
    for uuid, entry in acc.items():
        ops = entry["ops"]
        if int(serde.Op.DELETE) in ops and int(serde.Op.NEW) in ops:
            continue  # net no-op: created then deleted locally before syncing
        if int(serde.Op.DELETE) in ops:
            op = int(serde.Op.DELETE)
        elif int(serde.Op.NEW) in ops:
            op = int(serde.Op.NEW)
        else:
            op = int(serde.Op.EDIT)
        merged[uuid] = {"kind": entry["kind"], "op": op, "fields": entry["fields"]}
    return merged, seqs, uuids
