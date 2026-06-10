import pytest
from fastapi.testclient import TestClient

from daemon import sessions
from daemon.db import apply_migrations_sync, open_db
from daemon.main import app


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


def test_archive_hides_from_default_list_and_unarchive_restores():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    assert sessions.set_archived("s", True) is True
    assert sessions.list_sessions() == []
    assert [r["id"] for r in sessions.list_sessions(include_archived=True)] == ["s"]

    assert sessions.set_archived("s", False) is True
    assert [r["id"] for r in sessions.list_sessions()] == ["s"]


def test_soft_delete_hides_everywhere_and_restore_brings_back():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    assert sessions.set_deleted("s", True) is True
    assert sessions.list_sessions(include_archived=True) == []  # hidden even with archived shown

    assert sessions.set_deleted("s", False) is True
    assert [r["id"] for r in sessions.list_sessions()] == ["s"]


def test_lifecycle_toggle_reports_missing_session():
    assert sessions.set_archived("ghost", True) is False
    assert sessions.set_deleted("ghost", True) is False


def test_set_status_updates_and_reports_missing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    assert sessions.set_status("s", "ready") is True
    assert sessions.get_session("s")["status"] == "ready"
    assert sessions.set_status("ghost", "ready") is False


def test_set_agent_session_id_stores_and_reports_missing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    assert sessions.get_session("s")["agent_session_id"] is None  # unset at creation
    assert sessions.set_agent_session_id("s", "sdk-xyz") is True
    assert sessions.get_session("s")["agent_session_id"] == "sdk-xyz"
    assert sessions.set_agent_session_id("ghost", "sdk-xyz") is False


def test_archive_endpoint_removes_session_from_the_listing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        assert client.post("/sessions/s/archive").status_code == 200
        listed = client.get("/sessions").json()["sessions"]
    assert listed == []


def test_delete_endpoint_then_restore():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        assert client.delete("/sessions/s").status_code == 200
        assert client.get("/sessions").json()["sessions"] == []
        assert client.post("/sessions/s/restore").status_code == 200
        assert [r["id"] for r in client.get("/sessions").json()["sessions"]] == ["s"]


def test_lifecycle_endpoint_404s_on_missing_session():
    with TestClient(app) as client:
        assert client.post("/sessions/ghost/archive").status_code == 404
        assert client.delete("/sessions/ghost").status_code == 404


def test_get_session_returns_row_and_404s_on_missing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        resp = client.get("/sessions/s")
        assert resp.status_code == 200
        assert resp.json()["id"] == "s"
        assert resp.json()["status"] == "ready"
        assert client.get("/sessions/ghost").status_code == 404
