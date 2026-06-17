-- Schema v5: the message table — the persisted chat transcript.
--
-- A surface's conversation (the activity feed) lived only in the in-memory
-- ViewState, so it vanished on daemon restart. This table is the durable store:
-- one row per activity segment (user prompt, Claude's text, a tool/result line, a
-- rendered HTML artifact), written as it happens and replayed on connect.
--
-- `id` autoincrements, giving a stable insertion order to read back by. No foreign
-- key to `session`: a surface is an opaque string here (the in-memory store treats
-- it the same, and /dev/emit records to surfaces with no session row). `summary` is
-- a user prompt's outline-rail label, filled in after the row is written.

BEGIN;

CREATE TABLE message (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    surface    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    html       TEXT,
    summary    TEXT,
    created_at TEXT NOT NULL
);

-- Per-surface transcript read back in insertion order.
CREATE INDEX message_surface_id_idx ON message(surface, id);

COMMIT;
