-- Schema v11: durable on-disk screenshot filenames for a user turn.
--
-- Pasted/dropped screenshots were sent to the model but never persisted, so on a daemon
-- restart (or a browser reload) the transcript showed no image. `images` is the durable
-- home for the list of downscaled screenshot filenames the daemon writes under the
-- app-support `screenshots/` dir — a JSON array of "<uuid>.webp" strings. It's nullable
-- and NULL for every non-image row (the common case), mirroring `data`. The image bytes
-- live on disk, not in the DB, so the row stays small and the DB backups stay text-only.

BEGIN;

ALTER TABLE message ADD COLUMN images TEXT;

COMMIT;
