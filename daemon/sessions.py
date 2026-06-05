"""Repository for review sessions (the `session` table)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from daemon.db import open_db

_COLUMNS = (
    "id",
    "type",
    "title",
    "status",
    "repo",
    "branch",
    "worktree_path",
    "base_ref",
    "created_at",
    "updated_at",
    "archived_at",
    "deleted_at",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_review_session(
    *,
    worktree_path: str,
    base_ref: str,
    repo: str | None = None,
    branch: str | None = None,
    title: str | None = None,
) -> str:
    """Create a `type='review'` session in the `running` state; return its id."""
    conn = open_db()
    try:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        conn.execute(
            "INSERT INTO session (id, type, title, status, repo, branch, worktree_path, "
            "base_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                "review",
                title,
                "running",
                repo,
                branch,
                worktree_path,
                base_ref,
                now,
                now,
            ),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()


def list_sessions(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Sessions for the home page, newest-activity first, each with a findings
    summary (total + open). Soft-deleted sessions are always excluded; archived
    ones only when include_archived is False.

    A single LEFT JOIN + GROUP BY computes the counts (no per-session query).
    """
    where = "WHERE s.deleted_at IS NULL"
    if not include_archived:
        where += " AND s.archived_at IS NULL"
    select_cols = ", ".join(f"s.{c}" for c in _COLUMNS)
    sql = (
        f"SELECT {select_cols}, "
        "COUNT(f.id) AS findings_total, "
        # f.id IS NOT NULL guards the LEFT JOIN's null row for sessions with no
        # findings (whose f.disposition is also NULL but isn't an open finding).
        "COALESCE(SUM(CASE WHEN f.id IS NOT NULL AND f.disposition IS NULL THEN 1 ELSE 0 END), 0) "
        "AS findings_open "
        "FROM session s LEFT JOIN finding f ON f.session_id = s.id "
        f"{where} GROUP BY s.id ORDER BY s.updated_at DESC"
    )
    conn = open_db()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    sessions = []
    for row in rows:
        record = dict(zip(_COLUMNS, row[: len(_COLUMNS)], strict=True))
        record["findings_total"] = row[len(_COLUMNS)]
        record["findings_open"] = row[len(_COLUMNS) + 1]
        sessions.append(record)
    return sessions


def get_session(session_id: str) -> dict[str, Any] | None:
    conn = open_db()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM session WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(zip(_COLUMNS, row, strict=True)) if row else None
