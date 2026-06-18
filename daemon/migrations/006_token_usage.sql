-- Schema v6: the token_usage table — per-call LLM token accounting.
--
-- CVI makes several kinds of LLM call per session: the main agent turn, plus the
-- title-generation and prompt-summary sub-calls. We record one row per call so a
-- session's running token total (shown in the footer) survives a daemon restart and
-- a browser refresh, and so a per-prompt breakdown can be added later without a
-- backfill. A dedicated table (rather than columns on `message`) keeps session-level
-- calls like title generation — which have no prompt row — first-class.
--
-- `message_id` is the prompt row a call is attributed to (NULL for session-level
-- calls like title). No foreign key: a surface is an opaque string here, matching
-- the `message` table's own no-FK decision.

BEGIN;

CREATE TABLE token_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    surface       TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- 'turn' | 'title' | 'summary'
    message_id    INTEGER,                -- attributed prompt row; NULL = session-level
    output_tokens INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

-- Per-surface rollup (the session token total) reads by surface.
CREATE INDEX token_usage_surface_idx ON token_usage(surface);

COMMIT;
