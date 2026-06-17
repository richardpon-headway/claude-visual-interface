-- Schema v4: collapse to chat-only.
--
-- The review feature is gone, so its structures come out: the `finding` table
-- (the review dispositions store, already unused) and the review-only session
-- columns (repo/branch/worktree_path/base_ref). `type` now defaults to 'chat',
-- and any surviving review rows are converted to 'chat' so prior conversations
-- stay listed and usable. `agent_session_id` is kept — it now records a chat's
-- own SDK session for resume across restarts.
--
-- Copy-preserving: existing rows carry forward (INSERT ... SELECT). `finding` is
-- dropped first so no foreign key references `session` during the table rebuild.

BEGIN;

DROP TABLE IF EXISTS finding;

CREATE TABLE session_new (
    id               TEXT NOT NULL,
    type             TEXT NOT NULL DEFAULT 'chat',
    title            TEXT,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    archived_at      TEXT,
    deleted_at       TEXT,
    agent_session_id TEXT,
    PRIMARY KEY (id)
);

INSERT INTO session_new
    (id, type, title, status, created_at, updated_at, archived_at, deleted_at, agent_session_id)
SELECT
    id,
    CASE WHEN type = 'review' THEN 'chat' ELSE type END,
    title, status, created_at, updated_at, archived_at, deleted_at, agent_session_id
FROM session;

DROP TABLE session;
ALTER TABLE session_new RENAME TO session;

-- The home page lists sessions sorted by updated_at desc.
CREATE INDEX session_updated_at_idx ON session(updated_at);

COMMIT;
