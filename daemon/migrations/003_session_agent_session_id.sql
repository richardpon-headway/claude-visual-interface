-- Schema v3: link a surface to the Claude Agent SDK session that reviewed it.
--
-- The one-shot review and the interactive chat are separate SDK sessions. To let
-- chat *continue* the review (not start blank), the runner captures the SDK
-- session id from the review's result and stores it here; the chat client opens
-- with resume=<this id>. Nullable: unset at session creation, written when the
-- review's ResultMessage arrives, and absent for never-reviewed / pre-v3 rows
-- (those chats start fresh). Additive column — existing rows carry forward.

BEGIN;

ALTER TABLE session ADD COLUMN agent_session_id TEXT;

COMMIT;
