from daemon.db import _discover_migrations, apply_migrations_sync, open_db


def _table_columns(db_path, table):
    conn = open_db(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {row[1] for row in rows}


def test_migrations_create_session_schema(tmp_path):
    db_path = tmp_path / "cvi.db"
    apply_migrations_sync(db_path)

    columns = _table_columns(db_path, "session")
    assert columns == {
        "id",
        "type",
        "title",
        "status",
        "created_at",
        "updated_at",
        "archived_at",
        "deleted_at",
        "agent_session_id",
    }
    # The review feature's finding table is dropped by migration 004.
    assert _table_columns(db_path, "finding") == set()


def test_migrations_are_recorded(tmp_path):
    db_path = tmp_path / "cvi.db"
    apply_migrations_sync(db_path)

    conn = open_db(db_path)
    try:
        applied = {row[0] for row in conn.execute("SELECT name FROM _migration").fetchall()}
    finally:
        conn.close()
    assert "001_session.sql" in applied


def test_backup_taken_for_existing_db_then_skipped_when_fresh(tmp_path):
    db_path = tmp_path / "cvi.db"

    # First run: no DB file yet, so nothing to back up.
    apply_migrations_sync(db_path)
    assert list(tmp_path.glob("cvi.db.bak.*")) == []

    # Second run: the DB now exists and has no prior backup, so one is taken.
    apply_migrations_sync(db_path)
    assert len(list(tmp_path.glob("cvi.db.bak.*"))) == 1

    # Third run: the lone backup is fresh (< 24h), so the snapshot is skipped.
    apply_migrations_sync(db_path)
    assert len(list(tmp_path.glob("cvi.db.bak.*"))) == 1


def test_rerunning_migrations_is_a_noop(tmp_path):
    db_path = tmp_path / "cvi.db"
    apply_migrations_sync(db_path)
    conn = open_db(db_path)
    try:
        first = conn.execute("SELECT COUNT(*) FROM _migration").fetchone()[0]
    finally:
        conn.close()

    # Re-running applies nothing new.
    apply_migrations_sync(db_path)
    conn = open_db(db_path)
    try:
        second = conn.execute("SELECT COUNT(*) FROM _migration").fetchone()[0]
    finally:
        conn.close()

    # Re-running is a no-op: the count is unchanged and equals the number of
    # migration files on disk (every one applied exactly once).
    assert first == second == len(_discover_migrations())
