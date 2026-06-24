"""Credential storage for the Things Cloud account.

Prefers the system keyring (GNOME Keyring / Secret Service) when the optional
``keyring`` package is installed; otherwise falls back to a JSON file in the XDG
config directory with ``0600`` permissions. The fallback is documented as less
secure in the README.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .. import config

_SERVICE = "things4linux"
_KEY = "account"

try:  # optional dependency
    import keyring  # type: ignore

    _HAVE_KEYRING = True
except Exception:  # pragma: no cover - exercised only when keyring is absent
    _HAVE_KEYRING = False


@dataclass
class Credentials:
    email: str
    password: str
    history_key: str | None = None


def _file_path():
    return config.config_dir() / "credentials.json"


def save(creds: Credentials) -> None:
    blob = json.dumps(
        {
            "email": creds.email,
            "password": creds.password,
            "history_key": creds.history_key,
        }
    )
    if _HAVE_KEYRING:
        keyring.set_password(_SERVICE, _KEY, blob)
        return
    path = _file_path()
    # Create with restrictive perms before writing any secret bytes.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(blob)


def load() -> Credentials | None:
    blob: str | None = None
    if _HAVE_KEYRING:
        blob = keyring.get_password(_SERVICE, _KEY)
    else:
        path = _file_path()
        if path.exists():
            blob = path.read_text()
    if not blob:
        return None
    data = json.loads(blob)
    return Credentials(
        email=data["email"],
        password=data["password"],
        history_key=data.get("history_key"),
    )


def clear() -> None:
    if _HAVE_KEYRING:
        try:
            keyring.delete_password(_SERVICE, _KEY)
        except Exception:
            pass
    else:
        path = _file_path()
        if path.exists():
            path.unlink()
