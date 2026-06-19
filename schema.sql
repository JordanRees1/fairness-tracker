-- Fairness Tracker schema

CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    key      TEXT    UNIQUE NOT NULL,   -- stable id, e.g. 'jordan'
    name     TEXT    NOT NULL,          -- display name
    pin_hash TEXT    NOT NULL,          -- hashed login PIN
    count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,            -- ISO timestamp
    user_key  TEXT NOT NULL,            -- who (or 'admin')
    action    TEXT NOT NULL,            -- check | did | reset | adjust
    result    TEXT NOT NULL,            -- allowed | blocked | ok | note
    counts    TEXT                      -- JSON snapshot of both counts
);

CREATE INDEX IF NOT EXISTS idx_events_id ON events(id DESC);
