-- Things4Linux local store. Mirrors the subset of Things' model needed for the
-- MVP plus the bookkeeping the sync engine relies on (head index + change queue).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS task (
    uuid              TEXT PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT '',
    notes             TEXT NOT NULL DEFAULT '',
    type              INTEGER NOT NULL DEFAULT 0,   -- 0 task, 1 project, 2 heading
    status            INTEGER NOT NULL DEFAULT 0,   -- 0 todo, 2 cancelled, 3 completed
    destination       INTEGER NOT NULL DEFAULT 0,   -- 0 inbox, 1 anytime, 2 someday
    "index"           INTEGER NOT NULL DEFAULT 0,
    today_index       INTEGER NOT NULL DEFAULT 0,
    scheduled_date    INTEGER,                      -- the "when" date (epoch s)
    deadline          INTEGER,
    completion_date   INTEGER,
    creation_date     REAL,
    modification_date REAL,
    trashed           INTEGER NOT NULL DEFAULT 0,
    evening           INTEGER NOT NULL DEFAULT 0,
    area              TEXT,
    project           TEXT,
    heading           TEXT,
    dirty             INTEGER NOT NULL DEFAULT 0     -- has un-pushed local changes
);
CREATE INDEX IF NOT EXISTS task_by_project ON task(project);
CREATE INDEX IF NOT EXISTS task_by_area ON task(area);
CREATE INDEX IF NOT EXISTS task_by_dest ON task(destination);

CREATE TABLE IF NOT EXISTS area (
    uuid    TEXT PRIMARY KEY,
    title   TEXT NOT NULL DEFAULT '',
    "index" INTEGER NOT NULL DEFAULT 0,
    trashed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tag (
    uuid     TEXT PRIMARY KEY,
    title    TEXT NOT NULL DEFAULT '',
    shortcut TEXT,
    "index"  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS task_tag (
    task_uuid TEXT NOT NULL,
    tag_uuid  TEXT NOT NULL,
    PRIMARY KEY (task_uuid, tag_uuid)
);

CREATE TABLE IF NOT EXISTS checklist_item (
    uuid            TEXT PRIMARY KEY,
    task            TEXT,
    title           TEXT NOT NULL DEFAULT '',
    status          INTEGER NOT NULL DEFAULT 0,
    "index"         INTEGER NOT NULL DEFAULT 0,
    completion_date INTEGER
);

-- Single-row table holding the account's sync position.
CREATE TABLE IF NOT EXISTS sync_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    history_key TEXT,
    head_index  INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO sync_state (id, history_key, head_index) VALUES (1, NULL, 0);

-- Small key/value store: e.g. the entity generation (Task2 vs Task6) this
-- account's app uses, learned from the history so our writes match.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Locally-originated changes awaiting a /commit. ``fields`` is a JSON dict of the
-- changed internal field names -> values; the engine encodes it via serde.
CREATE TABLE IF NOT EXISTS change_queue (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid       TEXT NOT NULL,
    kind       TEXT NOT NULL,                       -- task / area / tag / checklist
    op         INTEGER NOT NULL,                    -- 0 new, 1 edit, 2 delete
    fields     TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);
