-- Schema v7: a user-set title override for sessions.
--
-- `title` holds the auto-generated title: it's written once the chat is named and
-- re-generated periodically by the title refresh. A user who renames a session needs
-- that choice to stick, so we keep it in a separate, nullable column rather than
-- letting the manual title fight the auto refresh over one field. Reads prefer
-- `user_title` when present and fall back to `title`, so auto-titling keeps refreshing
-- `title` freely and the override simply wins on display. NULL = no override (the
-- common case); auto-titling never touches this column.

BEGIN;

ALTER TABLE session ADD COLUMN user_title TEXT;

COMMIT;
