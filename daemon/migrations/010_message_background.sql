-- Schema v10: persist the background marker on each transcript segment.
--
-- Whether a segment belongs to an agent-initiated (background) turn — one the model
-- ran on its own after a background task finished, rather than as the current prompt's
-- reply — lived only in the in-memory ViewState and the live broadcast, so on a daemon
-- restart (or any reconnect that rebuilds from the DB) every replayed row came back as
-- foreground and lost its dimming + `↳ background` tag. `background` is the durable home
-- for that flag: an INTEGER 0/1, defaulting to 0 so every existing row reads foreground
-- (the common case) and only agent-initiated segments carry 1.

BEGIN;

ALTER TABLE message ADD COLUMN background INTEGER NOT NULL DEFAULT 0;

COMMIT;
