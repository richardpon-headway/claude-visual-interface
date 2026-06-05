"""Repository for review findings — the persisted state behind the upsert_finding
and set_disposition primitives.

A finding is a code-anchored review comment; its disposition is read back on a
re-run so findings aren't re-raised. JSON-shaped fields (anchor, actions) are
stored as TEXT. Functions are synchronous (stdlib sqlite3); async callers offload
them via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from daemon.db import open_db

# Column order shared by the SELECT and the row decoder.
_COLUMNS = (
    "id",
    "session_id",
    "file",
    "anchor",
    "severity",
    "title",
    "body",
    "suggested_patch",
    "source_lens",
    "actions",
    "disposition",
    "created_at",
    "updated_at",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dump(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


def upsert_finding(
    *,
    finding_id: str | None,
    session_id: str,
    file: str,
    title: str,
    body: str,
    severity: str | None = None,
    anchor: Any = None,
    suggested_patch: str | None = None,
    source_lens: str | None = None,
    actions: Any = None,
) -> str:
    """Create a finding (when finding_id is None/unknown) or update its content.

    An update does not touch `disposition` — that's set_disposition's job — so
    re-emitting a finding on a re-run preserves the user's decision.
    """
    conn = open_db()
    try:
        now = _now_iso()
        existing = None
        if finding_id is not None:
            row = conn.execute("SELECT id FROM finding WHERE id = ?", (finding_id,)).fetchone()
            existing = row[0] if row else None

        if existing is not None:
            conn.execute(
                "UPDATE finding SET file = ?, anchor = ?, severity = ?, title = ?, "
                "body = ?, suggested_patch = ?, source_lens = ?, actions = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    file,
                    _dump(anchor),
                    severity,
                    title,
                    body,
                    suggested_patch,
                    source_lens,
                    _dump(actions),
                    now,
                    existing,
                ),
            )
            conn.commit()
            return existing

        new_id = finding_id or str(uuid.uuid4())
        conn.execute(
            "INSERT INTO finding (id, session_id, file, anchor, severity, title, body, "
            "suggested_patch, source_lens, actions, disposition, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                session_id,
                file,
                _dump(anchor),
                severity,
                title,
                body,
                suggested_patch,
                source_lens,
                _dump(actions),
                None,
                now,
                now,
            ),
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def set_disposition(finding_id: str, value: str) -> bool:
    """Set a finding's disposition. Returns False if no such finding exists."""
    conn = open_db()
    try:
        cursor = conn.execute(
            "UPDATE finding SET disposition = ?, updated_at = ? WHERE id = ?",
            (value, _now_iso(), finding_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_findings(session_id: str) -> list[dict[str, Any]]:
    """All findings for a session, oldest first, with JSON fields decoded."""
    conn = open_db()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM finding WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_decode(row) for row in rows]


def _decode(row: tuple[Any, ...]) -> dict[str, Any]:
    record = dict(zip(_COLUMNS, row, strict=True))
    record["anchor"] = json.loads(record["anchor"]) if record["anchor"] else None
    record["actions"] = json.loads(record["actions"]) if record["actions"] else None
    return record
