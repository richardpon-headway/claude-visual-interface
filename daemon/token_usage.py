"""Repository for per-call LLM token accounting (the `token_usage` table).

One row per LLM call CVI makes on a surface — the main agent turn, plus the
title-generation and prompt-summary sub-calls. The session's running token total
is the sum across these rows, so it survives a daemon restart (rebuilt from here)
and a browser refresh. `message_id` attributes a call to the prompt that drove it
(NULL for session-level calls like title generation), so a per-prompt breakdown can
be added later without a backfill.
"""

from __future__ import annotations

from datetime import UTC, datetime

from daemon.db import open_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_usage(
    surface: str,
    kind: str,
    output_tokens: int,
    input_tokens: int,
    message_id: int | None = None,
) -> None:
    """Record one LLM call's token usage. `kind` is 'turn' | 'title' | 'summary';
    `message_id` is the attributed prompt row (None for session-level calls)."""
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO token_usage "
            "(surface, kind, message_id, output_tokens, input_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (surface, kind, message_id, output_tokens, input_tokens, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def session_totals(surface: str) -> tuple[int, int]:
    """The (output, input) token totals for a surface, summed across every recorded
    call. Returns (0, 0) for a surface with no usage yet."""
    conn = open_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(output_tokens), 0), COALESCE(SUM(input_tokens), 0) "
            "FROM token_usage WHERE surface = ?",
            (surface,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]), int(row[1])


def tokens_for_message(message_id: int) -> tuple[int, int]:
    """The (output, input) token totals attributed to one prompt row, summed across
    its turn and any sub-calls. Powers a future per-prompt display."""
    conn = open_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(output_tokens), 0), COALESCE(SUM(input_tokens), 0) "
            "FROM token_usage WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]), int(row[1])
