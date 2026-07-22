-- Schema v9: durable payload + answer for AskUserQuestion pickers.
--
-- A picker's structured payload (the tool-use id and the `questions`, including each
-- option's rich HTML `preview`) lived only in the in-memory ViewState, so on a daemon
-- restart the picker fell back to a plain text line and lost its rich options. `data`
-- is the durable JSON home for that payload ({ask_id, questions}); it's nullable and
-- NULL for every non-picker row (the common case). `answer` holds the chosen value
-- once the user picks — a separate, mutable column (written after the row, like
-- `summary`) so an answered picker re-renders locked after a restart. Both columns are
-- ignored by every other `kind`.

BEGIN;

ALTER TABLE message ADD COLUMN data TEXT;
ALTER TABLE message ADD COLUMN answer TEXT;

COMMIT;
