"""An in-memory stand-in for the Things Cloud history server, used by the engine
tests. Models the append-only history and the ancestor-index optimistic check."""

from __future__ import annotations

from typing import Any

from things4linux.sync.protocol import Account, HistorySlice, ThingsCloudError


class FakeCloud:
    def __init__(self, history_key: str = "HK-TEST"):
        self.history_key = history_key
        self.history: list[dict[str, Any]] = []  # each: {uuid: {t,e,p}}
        self.commits: list[dict[str, Any]] = []  # raw bodies received

    # -- ThingsClient interface -------------------------------------------------------
    def login(self, email: str, password: str) -> Account:
        if password == "wrong":
            from things4linux.sync.protocol import AuthError

            raise AuthError("authentication failed (401)")
        return Account(email=email, history_key=self.history_key, status="active")

    def pull(self, history_key: str, start_index: int) -> HistorySlice:
        assert history_key == self.history_key
        items = self.history[start_index:]
        return HistorySlice(
            items=items,
            start_index=start_index,
            end_index=len(self.history),
            schema=301,
        )

    def commit(self, history_key: str, ancestor_index: int, items: dict[str, Any]) -> int:
        assert history_key == self.history_key
        if ancestor_index != len(self.history):
            raise ThingsCloudError("stale ancestor index")
        self.commits.append(items)
        for uuid, env in items.items():
            self.history.append({uuid: env})
        return len(self.history)

    def close(self) -> None:
        pass

    # -- helpers for tests ------------------------------------------------------------
    def server_push(self, uuid: str, entity: str, op: int, payload: dict[str, Any]) -> None:
        """Simulate another device writing to the history."""
        self.history.append({uuid: {"t": op, "e": entity, "p": payload}})
