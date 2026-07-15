-- Schema v8: a per-session "star" flag for pinning favorites.
--
-- starred_at is a nullable timestamp: non-NULL = starred (the value is when it was
-- starred, leaving room for a future sort-by-starred); NULL = not starred, the
-- common case and the correct default for every existing row. Star is independent
-- of archived_at/deleted_at. Unlike those lifecycle flags, toggling star does NOT
-- bump updated_at (see daemon/sessions.py set_starred) — starring is organizational
-- metadata, not activity, so it must not reorder the list.

BEGIN;

ALTER TABLE session ADD COLUMN starred_at TEXT;

COMMIT;
