-- Schema v13: the per-segment verb for a "doing" lane entry.
--
-- A "doing" segment is Claude's own process narration — what it's doing and why — which
-- the browser renders as a dim, quiet lane set apart from reader-facing prose/artifacts.
-- Each such segment carries a short, free-text verb ("reading", "searching", "testing",
-- "thinking", …) shown as its chip. That verb lived only in the live broadcast, so on a
-- daemon restart a replayed "doing" row lost its chip. `verb` is the durable home for it:
-- a nullable TEXT, NULL for every non-"doing" row (the common case), mirroring
-- `data`/`images`/`pastes`.

BEGIN;

ALTER TABLE message ADD COLUMN verb TEXT;

COMMIT;
