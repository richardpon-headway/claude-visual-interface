-- Schema v2: the finding table.
--
-- A review = one conversation + a set of code-anchored findings. A finding is a
-- review comment anchored to a file (quoted snippet + range, fuzzy-relocatable),
-- carrying the disposition the user lands on. Dispositions are read back on a
-- re-run so findings aren't re-raised — the DB is the dispositions store.
--
-- anchor and actions are JSON (the available actions are whatever the review
-- skill emits, not a fixed set); severity/source_lens/disposition are free
-- strings for the same reason. upsert is keyed on the primary key `id`.

BEGIN;

CREATE TABLE finding (
    id              TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    file            TEXT NOT NULL,
    anchor          TEXT,            -- JSON: {snippet, range}
    severity        TEXT,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    suggested_patch TEXT,
    source_lens     TEXT,
    actions         TEXT,            -- JSON array of action names
    disposition     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
);

CREATE INDEX finding_session_id_idx ON finding(session_id);

COMMIT;
