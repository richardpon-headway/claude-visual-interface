import pytest

from daemon import sessions
from daemon.db import apply_migrations_sync, open_db


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


def _insert_session(session_id, *, updated_at, archived_at=None, deleted_at=None):
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session "
            "(id, type, status, created_at, updated_at, archived_at, deleted_at) "
            "VALUES (?, 'review', 'ready', 't', ?, ?, ?)",
            (session_id, updated_at, archived_at, deleted_at),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_finding(session_id, finding_id, *, disposition=None):
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO finding "
            "(id, session_id, file, title, body, disposition, created_at, updated_at) "
            "VALUES (?, ?, 'a.py', 't', 'b', ?, 't', 't')",
            (finding_id, session_id, disposition),
        )
        conn.commit()
    finally:
        conn.close()


def test_lists_newest_activity_first():
    _insert_session("older", updated_at="2026-01-01T00:00:00Z")
    _insert_session("newer", updated_at="2026-02-01T00:00:00Z")
    ids = [s["id"] for s in sessions.list_sessions()]
    assert ids == ["newer", "older"]


def test_includes_findings_summary():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    _insert_finding("s", "f1")  # open
    _insert_finding("s", "f2", disposition="dismissed")  # resolved
    row = sessions.list_sessions()[0]
    assert row["findings_total"] == 2
    assert row["findings_open"] == 1


def test_session_with_no_findings_reports_zero():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    row = sessions.list_sessions()[0]
    assert row["findings_total"] == 0
    assert row["findings_open"] == 0


def test_excludes_soft_deleted_always():
    _insert_session("live", updated_at="2026-01-02T00:00:00Z")
    _insert_session("gone", updated_at="2026-01-01T00:00:00Z", deleted_at="2026-01-03T00:00:00Z")
    assert [s["id"] for s in sessions.list_sessions(include_archived=True)] == ["live"]


def test_excludes_archived_unless_requested():
    _insert_session("live", updated_at="2026-01-02T00:00:00Z")
    _insert_session("filed", updated_at="2026-01-01T00:00:00Z", archived_at="2026-01-03T00:00:00Z")

    assert [s["id"] for s in sessions.list_sessions()] == ["live"]
    assert {s["id"] for s in sessions.list_sessions(include_archived=True)} == {"live", "filed"}
