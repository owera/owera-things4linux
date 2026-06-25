"""Low-level Things Cloud HTTP client (reverse-engineered, unofficial).

Only three operations are needed for two-way sync:

1. ``login``  -> ``GET /version/1/account/{email}`` with an ``Authorization:
   Password '<pw>'`` header. Returns account info including the ``history-key``.
2. ``pull``   -> ``GET /version/1/history/{key}/items?start-index=N``. Returns the
   slice of the history starting at ``N`` plus the new head index.
3. ``commit`` -> ``POST /version/1/history/{key}/commit?ancestor-index=N``. Writes
   a batch of item envelopes and returns the new server head index.

Everything here is synchronous (httpx.Client); the engine runs it on a worker
thread so the GTK main loop never blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .. import config


class ThingsCloudError(Exception):
    """Raised for any non-success response or transport failure."""


class AuthError(ThingsCloudError):
    """Raised specifically for 401/403 (bad credentials)."""


@dataclass
class Account:
    email: str
    history_key: str
    status: str


@dataclass
class HistorySlice:
    """A page of the remote history returned by :meth:`ThingsClient.pull`.

    The server returns items in pages (≤2500). ``head_index`` is the global head
    of the history (the response's ``current-item-index``) — the same value used
    as the commit ``ancestor-index``. ``next_index`` is where the *next* page
    starts (this page's ``start_index`` + the number of items returned); keep
    pulling from it until ``next_index >= head_index``.
    """

    items: list[dict[str, Any]]  # each: {uuid: {t, e, p}}
    start_index: int
    next_index: int
    head_index: int
    schema: int


def _sync_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Accept-Charset": "UTF-8",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": config.USER_AGENT,
        "Schema": config.SCHEMA_VERSION,
        "App-Id": config.THINGS_APP_ID,
        "App-Instance-Id": config.THINGS_APP_INSTANCE_ID,
        "Push-Priority": "5",
    }


class ThingsClient:
    """Thin synchronous wrapper over the Things Cloud history API."""

    def __init__(self, *, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or config.CLOUD_BASE_URL).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- lifecycle --------------------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ThingsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- requests ---------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:  # transport-level (DNS, timeout, ...)
            raise ThingsCloudError(f"network error: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthError(f"authentication failed ({resp.status_code})")
        if resp.status_code >= 400:
            raise ThingsCloudError(
                f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp

    def login(self, email: str, password: str) -> Account:
        """Verify credentials and fetch the account's ``history-key``."""
        # Auth scheme is ``Password <url-quoted-password>``. ``safe="'"`` leaves a
        # literal single quote in the password un-escaped (matches the macOS client).
        auth = "Password " + quote(password, safe="'")
        url = f"/version/1/account/{quote(email)}"
        resp = self._request("GET", url, headers={"Authorization": auth})
        data = resp.json()
        key = data.get("history-key")
        if not key:
            raise ThingsCloudError("login succeeded but no history-key was returned")
        return Account(email=email, history_key=key, status=data.get("status", ""))

    def pull(self, history_key: str, start_index: int) -> HistorySlice:
        """Fetch history items from ``start_index`` onwards."""
        url = f"/version/1/history/{history_key}/items"
        resp = self._request(
            "GET", url, params={"start-index": str(start_index)}, headers=_sync_headers()
        )
        data = resp.json()
        items = data.get("items", [])
        return HistorySlice(
            items=items,
            start_index=start_index,
            next_index=start_index + len(items),
            head_index=int(data.get("current-item-index", start_index)),
            schema=int(data.get("schema", 0)),
        )

    def commit(
        self, history_key: str, ancestor_index: int, items: dict[str, Any]
    ) -> int:
        """Write ``items`` (``{uuid: {t,e,p}}``) and return the new head index."""
        url = f"/version/1/history/{history_key}/commit"
        resp = self._request(
            "POST",
            url,
            params={"ancestor-index": str(ancestor_index), "_cnt": str(len(items))},
            headers=_sync_headers(),
            json=items,
        )
        data = resp.json()
        # The server has used both spellings across versions.
        head = data.get("server-head-index", data.get("ServerHeadIndex"))
        if head is None:
            raise ThingsCloudError(f"commit response missing head index: {data}")
        return int(head)
