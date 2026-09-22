-- Schema v12: durable large pasted-text blocks for a user turn.
--
-- A large paste in the composer is lifted into its own chip and, until now, was flattened
-- back into the message text at send time — so on a daemon restart (or a browser reload)
-- the transcript replayed one opaque blob instead of the typed prompt plus each paste.
-- `pastes` is the durable home for a user turn's large pasted blocks — a JSON array of
-- strings, one per chip, in order. It's nullable and NULL for every non-paste row (the
-- common case), mirroring `images`/`data`.

BEGIN;

ALTER TABLE message ADD COLUMN pastes TEXT;

COMMIT;
