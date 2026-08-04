"""Repository for the persisted chat transcript (the `message` table).

One row per activity segment on a surface, written through `record_activity` as the
conversation happens and replayed on connect so a transcript survives a daemon
restart. A surface is an opaque string (no foreign key), mirroring the in-memory
view-state store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from daemon import sessions
from daemon.db import open_db

_COLUMNS = (
    "id",
    "surface",
    "kind",
    "text",
    "html",
    "summary",
    "data",
    "answer",
    "background",
    "created_at",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_message(
    surface: str,
    kind: str,
    text: str,
    html: str | None = None,
    data: str | None = None,
    background: bool = False,
) -> int:
    """Append one transcript segment for a surface; return its new row id (used to
    fill in a prompt's summary later). `html` carries an artifact's page; `data` carries
    a picker's structured payload as a JSON string ({ask_id, questions}); `background`
    marks a segment from an agent-initiated (background) turn so its dimming + tag
    survive a reload.

    A user prompt (`kind == "user"`) resurfaces the session if it had been
    auto-archived — chatting in a chat should bring it back to the list. This fires on
    the user's own message, not on the assistant/tool/artifact segments that follow."""
    conn = open_db()
    try:
        cursor = conn.execute(
            "INSERT INTO message (surface, kind, text, html, data, background, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (surface, kind, text, html, data, int(background), _now_iso()),
        )
        conn.commit()
        message_id = int(cursor.lastrowid)
    finally:
        conn.close()
    if kind == "user":
        sessions.resurface_if_archived(surface)
    return message_id


def set_message_answer(message_id: int, answer: str) -> bool:
    """Record a picker's chosen value on its already-written message row so an answered
    picker re-renders locked after a restart. Returns False if no such row."""
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE message SET answer = ? WHERE id = ?",
            (answer, message_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_message_summary(message_id: int, summary: str) -> bool:
    """Attach a generated outline-rail summary to an already-written message.
    Returns False if no such row."""
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE message SET summary = ? WHERE id = ?",
            (summary, message_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_messages(surface: str) -> list[dict[str, Any]]:
    """A surface's full transcript, oldest-first (insertion order)."""
    select_cols = ", ".join(_COLUMNS)
    conn = open_db()
    try:
        rows = conn.execute(
            f"SELECT {select_cols} FROM message WHERE surface = ? ORDER BY id",
            (surface,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]
