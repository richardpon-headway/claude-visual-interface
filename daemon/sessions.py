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
