"""Application-wide constants, paths, and the Things-compatible id generator.

Kept dependency-free on purpose: we replace ``platformdirs`` with a tiny XDG
helper and ``shortuuid`` with an inline base-57 encoder so the app runs against
a stock system Python that only ships PyGObject + httpx.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

APP_ID = "com.culturedcode.ThingsMac"
APP_NAME = "Things4Linux"
APPLICATION_ID = "io.github.things4linux.Things4Linux"

# --- Things Cloud protocol constants -------------------------------------------------
# Base URL for the (unofficial, reverse-engineered) Things Cloud API.
CLOUD_BASE_URL = "https://cloud.culturedcode.com"
# Schema version the desktop client advertises. Bump if the server rejects writes.
SCHEMA_VERSION = "301"
# Identifies the client to the server; mimics the macOS app so writes are accepted.
THINGS_APP_ID = os.environ.get("THINGS4LINUX_APP_ID", "com.culturedcode.ThingsMac")
THINGS_APP_INSTANCE_ID = f"-{THINGS_APP_ID}"
USER_AGENT = os.environ.get("THINGS4LINUX_USER_AGENT", "ThingsMac/31008003")

# How often the background engine polls Things Cloud for remote changes (seconds).
SYNC_POLL_INTERVAL = 30


# --- XDG paths -----------------------------------------------------------------------
def _xdg(env: str, default: str) -> Path:
    base = os.environ.get(env)
    root = Path(base) if base else Path.home() / default
    return root / "things4linux"


def data_dir() -> Path:
    d = _xdg("XDG_DATA_HOME", ".local/share")
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    d = _xdg("XDG_CONFIG_HOME", ".config")
    d.mkdir(parents=True, exist_ok=True)
    return d


def database_path() -> Path:
    return data_dir() / "things.db"


# --- Things-compatible identifiers ---------------------------------------------------
# Things uses 22-character base-57 identifiers (the alphabet shortuuid uses by
# default — ambiguous characters 0/O/1/I/l removed). We replicate it exactly so
# the ids we generate are indistinguishable from those a Things client makes.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ID_LENGTH = 22


def new_id() -> str:
    """Return a fresh 22-char Things-style identifier."""
    number = uuid.uuid4().int
    base = len(_ALPHABET)
    chars: list[str] = []
    while number:
        number, rem = divmod(number, base)
        chars.append(_ALPHABET[rem])
    out = "".join(reversed(chars))
    return out.rjust(_ID_LENGTH, _ALPHABET[0])[:_ID_LENGTH]
