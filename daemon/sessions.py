"""Repository for chat sessions (the `session` table)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from daemon.db import open_db

# The placeholder title a chat is born with, until auto-titling replaces it. Single
# source of truth: create_chat_session writes it, and the auto-title guards
# (set_generated_title's WHERE, agent_session's needs_title) match against it — they
# must not drift.
DEFAULT_CHAT_TITLE = "New chat"

_COLUMNS = (
    "id",
    "type",
    "title",
    "status",
    "created_at",
    "updated_at",
    "archived_at",
    "deleted_at",
    "agent_session_id",
    "user_title",
    "starred_at",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def effective_title(session: dict[str, Any]) -> str | None:
    """The title to display for a session: the user's manual override when set,
    otherwise the auto-generated title. Single source of truth so every surface
    (home list, header, browser tab, live broadcasts) agrees."""
    return session.get("user_title") or session.get("title")


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Map a `session` row to a dict and resolve `title` to the effective title, so
    callers read one already-resolved field and never have to coalesce themselves.
    The raw `user_title` stays on the dict for callers that need the override itself
    (e.g. seeding a rename input)."""
    session = dict(zip(_COLUMNS, row, strict=True))
    session["title"] = effective_title(session)
    return session


def create_chat_session(title: str | None = None) -> str:
    """Create a `type='chat'` session, ready to converse; return its new id."""
    conn = open_db()
    try:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        conn.execute(
            "INSERT INTO session (id, type, title, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "chat", title or DEFAULT_CHAT_TITLE, "ready", now, now),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()


def open_or_create_chat() -> str:
    """The chat to drop into on launch: reuse the newest empty 'New chat' if one exists,
    else create a fresh one. Empty = a live (not archived/deleted) chat still on the
    default title with no messages. Reusing avoids piling up empty sessions on every
    launch/refresh."""
    conn = open_db()
    try:
        row = conn.execute(
            "SELECT id FROM session "
            "WHERE type = 'chat' AND title = ? "
            "AND archived_at IS NULL AND deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM message WHERE message.surface = session.id) "
            "ORDER BY updated_at DESC LIMIT 1",
            (DEFAULT_CHAT_TITLE,),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return str(row[0])
    return create_chat_session()


def list_sessions(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Sessions for the home page, newest-activity first. Soft-deleted sessions are
    always excluded; archived ones only when include_archived is False."""
    where = "WHERE deleted_at IS NULL"
    if not include_archived:
        where += " AND archived_at IS NULL"
    select_cols = ", ".join(_COLUMNS)
    sql = f"SELECT {select_cols} FROM session {where} ORDER BY updated_at DESC"
    conn = open_db()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def _set_lifecycle_timestamp(session_id: str, column: str, on: bool) -> bool:
    """Set (on) or clear (off) a lifecycle timestamp column. Returns False if no
    such session. `column` is an internal constant, never user input."""
    now = _now_iso()
    conn = open_db()
    try:
        cursor = conn.execute(
            f"UPDATE session SET {column} = ?, updated_at = ? WHERE id = ?",
            (now if on else None, now, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_generated_title(session_id: str, title: str) -> bool:
    """Apply an auto-generated title, but only while the chat is still untitled (the
    default placeholder or NULL). The conditional WHERE makes this atomic: of several
    concurrent titling attempts, the first to commit wins and later ones match nothing
    — so a winner can't be clobbered, and a user-set title is never overwritten.
    Returns True only when this call actually set the title. Bumps updated_at."""
    now = _now_iso()
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE session SET title = ?, updated_at = ? "
            "WHERE id = ? AND (title IS NULL OR title = ?)",
            (title, now, session_id, DEFAULT_CHAT_TITLE),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def overwrite_title(session_id: str, title: str) -> None:
    """Unconditionally replace a session's title (used by the periodic title refresh,
    which always overwrites the previously generated title). Unlike set_generated_title
    there is no title-state guard — there is no rename UI today, so no user-set title to
    protect. Bumps updated_at."""
    now = _now_iso()
    conn = open_db()
    try:
        conn.execute(
            "UPDATE session SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_user_title(session_id: str, title: str) -> bool:
    """Store a user-provided title override. Auto-titling keeps writing and refreshing
    `title` untouched; reads (via effective_title) prefer this override when present.
    Returns False if no such session. Bumps updated_at."""
    now = _now_iso()
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE session SET user_title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_agent_session_id(session_id: str, agent_session_id: str) -> bool:
    """Store the Claude Agent SDK session id this chat is running under, so it can
    resume after an idle-close or daemon restart. Returns False if no such session.
    Bumps updated_at."""
    now = _now_iso()
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE session SET agent_session_id = ?, updated_at = ? WHERE id = ?",
            (agent_session_id, now, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_archived(session_id: str, archived: bool) -> bool:
    return _set_lifecycle_timestamp(session_id, "archived_at", archived)


def set_deleted(session_id: str, deleted: bool) -> bool:
    return _set_lifecycle_timestamp(session_id, "deleted_at", deleted)


def set_starred(session_id: str, starred: bool) -> bool:
    """Star or unstar a session by toggling starred_at. Unlike the lifecycle toggles
    above, this deliberately does NOT bump updated_at: a star is organizational
    metadata, not activity, so it must not reorder the list. Returns False if no such
    session."""
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE session SET starred_at = ? WHERE id = ?",
            (_now_iso() if starred else None, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_session(session_id: str) -> dict[str, Any] | None:
    conn = open_db()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM session WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None
