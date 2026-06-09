import os

import pytest
from fastapi.testclient import TestClient

from daemon import files
from daemon.db import apply_migrations_sync, open_db
from daemon.files import FileOutsideWorktreeError, read_worktree_file
from daemon.main import app

SESSION = "file-session"


@pytest.fixture
def worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "a.py").write_text("print('hello')\n")
    (wt / "sub").mkdir()
    (wt / "sub" / "b.py").write_text("x = 1\n")
    return wt


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch, worktree):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, worktree_path, created_at, updated_at) "
            "VALUES (?, 'review', 'ready', ?, 't', 't')",
            (SESSION, str(worktree)),
        )
        conn.commit()
    finally:
        conn.close()


# --- read_worktree_file (the safety-critical core) --------------------------------

def test_reads_a_text_file(worktree):
    result = read_worktree_file(str(worktree), "a.py")
    assert result is not None
    assert result.content == "print('hello')\n"
    assert result.reason is None


def test_missing_file_returns_none(worktree):
    assert read_worktree_file(str(worktree), "nope.py") is None


def test_relative_escape_is_rejected(worktree, tmp_path):
    (tmp_path / "secret.txt").write_text("top secret")
    with pytest.raises(FileOutsideWorktreeError):
        read_worktree_file(str(worktree), "../secret.txt")


def test_absolute_path_is_rejected(worktree):
    with pytest.raises(FileOutsideWorktreeError):
        read_worktree_file(str(worktree), "/etc/hosts")


def test_symlink_out_of_worktree_is_rejected(worktree, tmp_path):
    (tmp_path / "outside.txt").write_text("nope")
    os.symlink(tmp_path / "outside.txt", worktree / "link.txt")
    with pytest.raises(FileOutsideWorktreeError):
        read_worktree_file(str(worktree), "link.txt")


def test_binary_file_is_reported(worktree):
    (worktree / "bin.dat").write_bytes(b"\x00\x01\x02")
    result = read_worktree_file(str(worktree), "bin.dat")
    assert result is not None and result.content is None and result.reason == "binary"


def test_oversized_file_is_reported(worktree, monkeypatch):
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 4)
    (worktree / "big.txt").write_text("way more than four bytes")
    result = read_worktree_file(str(worktree), "big.txt")
    assert result is not None and result.content is None and result.reason == "too_large"


# --- the HTTP endpoint (session lookup + wiring) ----------------------------------

def test_endpoint_serves_file_content():
    with TestClient(app) as client:
        response = client.get(f"/sessions/{SESSION}/file", params={"path": "sub/b.py"})
    assert response.status_code == 200
    assert response.json() == {"path": "sub/b.py", "content": "x = 1\n", "reason": None}


def test_endpoint_404s_on_escape_and_missing():
    with TestClient(app) as client:
        def status(session_id, path):
            return client.get(f"/sessions/{session_id}/file", params={"path": path}).status_code

        assert status(SESSION, "../x") == 404  # escape
        assert status(SESSION, "nope.py") == 404  # missing file
        assert status("ghost", "a.py") == 404  # missing session
