-- Schema v1: the session table.
--
-- A session is one Claude visual surface. `type` is present from day one so
-- non-review surfaces slot in later without a schema change; v1 only writes
-- type='review'. Review-specific columns (repo/branch/worktree_path/base_ref)
-- and the lifecycle timestamps (title/archived_at/deleted_at) are nullable so
-- a future non-review surface need not carry dummy values.
--
-- Copy-preserving by default: a later schema-changing migration must carry
-- existing rows forward (INSERT ... SELECT) — sessions hold user input.

BEGIN;

CREATE TABLE session (
    id            TEXT NOT NULL,
    type          TEXT NOT NULL DEFAULT 'review',
    title         TEXT,
    status        TEXT NOT NULL,
    repo          TEXT,
    branch        TEXT,
    worktree_path TEXT,
    base_ref      TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    archived_at   TEXT,
    deleted_at    TEXT,
    PRIMARY KEY (id)
);

-- The home page lists sessions sorted by updated_at desc.
CREATE INDEX session_updated_at_idx ON session(updated_at);

COMMIT;
