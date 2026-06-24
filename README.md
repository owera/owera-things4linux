# Things4Linux

A native Linux desktop clone of [Things 3](https://culturedcode.com/things/) that
**syncs two-way with your Things Cloud account**, built with Python + GTK4 /
libadwaita.

> ⚠️ **Unofficial.** Things Cloud has no public API. Things4Linux talks to it
> using a community-**reverse-engineered** protocol. It is not affiliated with or
> endorsed by Cultured Code, may break when the service changes, and could carry
> some account/ToS risk. **Use a secondary Things Cloud account while evaluating,
> and keep a backup.** See [Safety](#safety).

![three-pane layout: sidebar of lists + areas, task list, task editor]

## Features (MVP)

- Built-in lists: **Inbox, Today** (with *This Evening*), **Upcoming, Anytime,
  Someday, Logbook, Trash**.
- **Areas → Projects → To-Dos** hierarchy in the sidebar.
- Create / edit / complete / trash to-dos; notes, a "When" date, and a deadline.
- **Empty Trash** to permanently delete trashed items (syncs the deletion).
- **Offline-first**: a local SQLite database is the source of truth; the app is
  fully usable with no network and reconciles when it reconnects.
- **Two-way Things Cloud sync** running in the background.

Planned next: tags, checklists, project headings, repeating to-dos, reminders,
drag-and-drop reordering, and a global Quick Entry hotkey.

## How it works

```
GTK UI  ⇄  db.store (SQLite, source of truth)  ⇄  sync.engine  ⇄  Things Cloud
```

- `things4linux/sync/protocol.py` — the Things Cloud HTTP client (login →
  `history-key`, pull history items by `start-index`, push via `/commit`).
- `things4linux/sync/serde.py` — translates Things' cryptic two-letter wire
  fields (`tt`=title, `ss`=status, `st`=destination, `sr`=when, `dd`=deadline …)
  to/from our model.
- `things4linux/db/store.py` — local store + the queries behind each list.
- `things4linux/sync/engine.py` — background pull/push loop reconciled through a
  monotonic history index.

### Protocol notes (verified against a live account)

- **Auth:** `GET /version/1/account/{email}` with header
  `Authorization: Password <url-quoted-password>` (the password is *not* wrapped
  in quotes). Returns the `history-key`.
- **Read:** `GET /version/1/history/{key}/items?start-index=N`. A pull from `0`
  returns a *compacted base snapshot*; you receive newer writes by pulling
  **incrementally from your last head** (`current-item-index`). The engine keeps a
  persistent head and always pulls forward, so a synced client reliably sees all
  remote changes.
- **Write:** `POST /version/1/history/{key}/commit?ancestor-index=H` where `H` is
  your current head. A **create must send the *complete* object** — a partial
  `NewBody` is silently orphaned by the server; edits send only changed fields.
- **Delete:** trashing is an edit that sets `tr=true`; *permanent* deletion
  (Empty Trash) is a commit with op `t=2` and an empty payload `{}` on the same
  entity — Things Cloud uses no separate tombstone entity.
- **Entity generations:** Things tags entities with a generation number
  (`Task`/`Task2`/`Task6`, `Tag`/`Tag2`/`Tag3`, `Area`/`Area2`) that varies by
  account/app version. We classify by stripping the trailing digits, and **learn
  which generation to write** from your own history so the official apps accept
  our writes.

## Requirements

System packages (the GTK stack is **not** installed from pip):

```bash
# Debian / Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                 libgtk-4-1 libadwaita-1-0

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita
```

Python packages:

```bash
pip install httpx          # required
pip install keyring        # optional — secure credential storage (see Safety)
```

> The only hard Python dependency is **httpx**; `shortuuid`, `platformdirs`, and
> `keyring` are intentionally avoided or optional so the app runs on a stock
> distro Python that already ships PyGObject.

## Running

From a checkout:

```bash
python3 -m things4linux
```

Or install it:

```bash
pip install .
things4linux
```

On first launch you'll be asked for your Things Cloud email and password. They
are used once to fetch your account's sync key; afterwards sync uses the key, not
your password.

## Safety

- **Test with a secondary account first.** This is reverse-engineered software
  writing to your live task data.
- **Back up your history** before the first write — e.g. export your data from
  the official Things app on another device.
- **Credential storage:** if the optional `keyring` package is installed,
  credentials go to the system secret store (GNOME Keyring / Secret Service).
  Otherwise they fall back to `~/.config/things4linux/credentials.json` with
  `0600` permissions — less secure; install `keyring` if that matters to you.
- Local data lives in `~/.local/share/things4linux/things.db`. Delete it to start
  a clean re-sync (your cloud data is untouched).

## Development

```bash
# run the test suite (stdlib unittest — no pytest needed)
python3 -m unittest discover -t . -s tests

# headless GUI smoke test
xvfb-run python3 -m things4linux   # needs a Things Cloud login to do anything live
```

Tests cover the serde field mapping, the store's view queries and dirty/queue
bookkeeping, and the sync engine end-to-end against an in-memory fake of the
Things Cloud history server (including the stale-ancestor retry path).

## License

MIT.
