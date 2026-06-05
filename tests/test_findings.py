import pytest

from daemon import findings
from daemon.db import apply_migrations_sync, open_db


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES ('sess', 'review', 'running', 't', 't')",
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_creates_finding_table():
    conn = open_db()
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(finding)").fetchall()}
    finally:
        conn.close()
    assert cols == {
        "id", "session_id", "file", "anchor", "severity", "title", "body",
        "suggested_patch", "source_lens", "actions", "disposition", "created_at", "updated_at",
    }


def test_create_returns_an_id_and_round_trips_json_fields():
    fid = findings.upsert_finding(
        finding_id=None,
        session_id="sess",
        file="a.py",
        title="t",
        body="b",
        severity="high",
        anchor={"snippet": "x = 1", "range": {"start": 1, "end": 1}},
        actions=["dismiss", "fix"],
    )
    rows = findings.list_findings("sess")
    assert len(rows) == 1
    assert rows[0]["id"] == fid
    assert rows[0]["anchor"] == {"snippet": "x = 1", "range": {"start": 1, "end": 1}}
    assert rows[0]["actions"] == ["dismiss", "fix"]
    assert rows[0]["disposition"] is None


def test_upsert_by_id_updates_content_but_preserves_disposition():
    fid = findings.upsert_finding(
        finding_id=None, session_id="sess", file="a.py", title="t", body="b"
    )
    findings.set_disposition(fid, "dismissed")

    same = findings.upsert_finding(
        finding_id=fid, session_id="sess", file="a.py", title="new title", body="b2"
    )
    assert same == fid
    rows = findings.list_findings("sess")
    assert len(rows) == 1  # updated in place, not duplicated
    assert rows[0]["title"] == "new title"
    assert rows[0]["disposition"] == "dismissed"  # re-emit preserves the decision


def test_set_disposition_reports_missing_finding():
    assert findings.set_disposition("does-not-exist", "dismiss") is False
