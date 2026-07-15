import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from daemon import messages, sessions
from daemon.db import apply_migrations_sync, open_db
from daemon.main import app


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    # The rename endpoint now writes a token-monitor sidecar; keep it in the tmp dir.
    monkeypatch.setenv("CVI_TOKEN_MONITOR_SIDECAR_DIR", str(tmp_path / "session-meta"))
    apply_migrations_sync()


def _insert_session(session_id, *, updated_at, archived_at=None, deleted_at=None, starred_at=None):
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session "
            "(id, type, status, created_at, updated_at, archived_at, deleted_at, starred_at) "
            "VALUES (?, 'chat', 'ready', 't', ?, ?, ?, ?)",
            (session_id, updated_at, archived_at, deleted_at, starred_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_create_chat_session_is_ready_with_a_default_title():
    session_id = sessions.create_chat_session()
    row = sessions.get_session(session_id)
    assert row["type"] == "chat"
    assert row["status"] == "ready"
    assert row["title"] == "New chat"  # default label so the list row isn't a raw uuid


def test_create_chat_session_honors_a_title():
    session_id = sessions.create_chat_session("scratchpad")
    assert sessions.get_session(session_id)["title"] == "scratchpad"


def test_create_chat_endpoint_returns_a_ready_chat_session():
    with TestClient(app) as client:
        resp = client.post("/chats")
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
    row = sessions.get_session(session_id)
    assert (row["type"], row["status"]) == ("chat", "ready")


def test_create_chat_endpoint_honors_a_title():
    with TestClient(app) as client:
        session_id = client.post("/chats", json={"title": "scratchpad"}).json()["session_id"]
    assert sessions.get_session(session_id)["title"] == "scratchpad"


def test_open_or_create_creates_when_no_reusable_chat():
    session_id = sessions.open_or_create_chat()
    row = sessions.get_session(session_id)
    assert (row["type"], row["title"]) == ("chat", "New chat")


def test_open_or_create_reuses_the_newest_empty_chat():
    older = sessions.create_chat_session()
    newer = sessions.create_chat_session()
    # Both are empty "New chat" sessions → reuse the newest, create nothing new.
    assert sessions.open_or_create_chat() == newer
    assert sessions.list_sessions() and len(sessions.list_sessions()) == 2  # no third row
    assert older != newer


def test_open_or_create_skips_a_chat_that_has_messages():
    used = sessions.create_chat_session()
    messages.append_message(used, "user", "hello")
    opened = sessions.open_or_create_chat()
    assert opened != used  # a fresh chat, since `used` is no longer empty
    assert sessions.get_session(opened)["title"] == "New chat"


def test_open_or_create_skips_titled_archived_and_deleted_chats():
    sessions.create_chat_session("Renamed")  # not on the default title → not reusable
    archived = sessions.create_chat_session()
    sessions.set_archived(archived, True)
    deleted = sessions.create_chat_session()
    sessions.set_deleted(deleted, True)

    opened = sessions.open_or_create_chat()
    assert opened not in {archived, deleted}
    assert sessions.get_session(opened)["title"] == "New chat"


def test_open_chat_endpoint_reuses_on_repeat():
    with TestClient(app) as client:
        first = client.post("/chats/open")
        assert first.status_code == 200
        first_id = first.json()["session_id"]
        # No messages added → the second open reuses the same empty chat.
        second_id = client.post("/chats/open").json()["session_id"]
    assert first_id == second_id


def test_lists_newest_activity_first():
    _insert_session("older", updated_at="2026-01-01T00:00:00Z")
    _insert_session("newer", updated_at="2026-02-01T00:00:00Z")
    ids = [s["id"] for s in sessions.list_sessions()]
    assert ids == ["newer", "older"]


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


def test_set_starred_toggles_without_bumping_updated_at():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")

    assert sessions.set_starred("s", True) is True
    row = sessions.get_session("s")
    assert row["starred_at"] is not None
    # Starring is metadata, not activity — updated_at (and list ordering) must not move.
    assert row["updated_at"] == "2026-01-01T00:00:00Z"

    assert sessions.set_starred("s", False) is True
    row = sessions.get_session("s")
    assert row["starred_at"] is None
    assert row["updated_at"] == "2026-01-01T00:00:00Z"


def test_set_starred_reports_missing_session():
    assert sessions.set_starred("ghost", True) is False


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


def test_set_generated_title_sets_only_while_untitled():
    chat = sessions.create_chat_session()  # title == "New chat"
    assert sessions.set_generated_title(chat, "Fix the parser") is True
    assert sessions.get_session(chat)["title"] == "Fix the parser"

    # A later attempt can't clobber the now-set title (the race / overwrite guard).
    assert sessions.set_generated_title(chat, "Something else") is False
    assert sessions.get_session(chat)["title"] == "Fix the parser"


def test_set_generated_title_fills_a_null_title():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")  # title is NULL
    assert sessions.set_generated_title("s", "A title") is True
    assert sessions.get_session("s")["title"] == "A title"


def test_set_generated_title_reports_missing_session():
    assert sessions.set_generated_title("ghost", "x") is False


def test_overwrite_title_replaces_an_existing_title():
    chat = sessions.create_chat_session()
    assert sessions.set_generated_title(chat, "First title") is True
    before = sessions.get_session(chat)["updated_at"]

    # The refresh path overwrites unconditionally, unlike set_generated_title's guard.
    sessions.overwrite_title(chat, "Refreshed title")
    row = sessions.get_session(chat)
    assert row["title"] == "Refreshed title"
    assert row["updated_at"] >= before


def test_set_user_title_overrides_the_displayed_title():
    chat = sessions.create_chat_session()
    assert sessions.set_generated_title(chat, "Auto title") is True
    assert sessions.set_user_title(chat, "My name") is True
    # The override wins on reads, while the raw auto title is preserved underneath.
    row = sessions.get_session(chat)
    assert row["title"] == "My name"
    assert row["user_title"] == "My name"


def test_set_user_title_reports_missing_session():
    assert sessions.set_user_title("ghost", "x") is False


def test_user_title_survives_a_later_auto_refresh():
    chat = sessions.create_chat_session()
    assert sessions.set_user_title(chat, "Pinned name") is True
    # The periodic refresh keeps rewriting the auto title, but the override still wins.
    sessions.overwrite_title(chat, "Refreshed auto title")
    assert sessions.get_session(chat)["title"] == "Pinned name"


def test_effective_title_falls_back_to_auto_title_when_no_override():
    chat = sessions.create_chat_session()
    sessions.overwrite_title(chat, "Auto title")
    row = sessions.get_session(chat)
    assert row["user_title"] is None
    assert row["title"] == "Auto title"  # falls back to the auto title


def test_rename_endpoint_sets_override_and_404s_on_missing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        assert client.post("/sessions/s/rename", json={"title": "Renamed"}).status_code == 200
        assert client.get("/sessions/s").json()["title"] == "Renamed"
        assert client.post("/sessions/ghost/rename", json={"title": "x"}).status_code == 404


def test_rename_writes_token_monitor_sidecar():
    chat = sessions.create_chat_session("Auto title")
    sessions.set_agent_session_id(chat, "sdk-renamed")
    with TestClient(app) as client:
        resp = client.post(f"/sessions/{chat}/rename", json={"title": "Pinned name"})
        assert resp.status_code == 200
    sidecar = Path(os.environ["CVI_TOKEN_MONITOR_SIDECAR_DIR"]) / "sdk-renamed.json"
    assert json.loads(sidecar.read_text())["topic"] == "Pinned name"


def test_rename_endpoint_rejects_an_empty_title():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        assert client.post("/sessions/s/rename", json={"title": "   "}).status_code == 422


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


def test_star_endpoint_round_trip_and_keeps_session_listed():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        assert client.post("/sessions/s/star").status_code == 200
        assert client.get("/sessions/s").json()["starred_at"] is not None
        # Starring is independent of archive/delete — the session stays in the listing.
        assert [r["id"] for r in client.get("/sessions").json()["sessions"]] == ["s"]

        assert client.post("/sessions/s/unstar").status_code == 200
        assert client.get("/sessions/s").json()["starred_at"] is None


def test_lifecycle_endpoint_404s_on_missing_session():
    with TestClient(app) as client:
        assert client.post("/sessions/ghost/archive").status_code == 404
        assert client.delete("/sessions/ghost").status_code == 404
        assert client.post("/sessions/ghost/star").status_code == 404


def test_get_session_returns_row_and_404s_on_missing():
    _insert_session("s", updated_at="2026-01-01T00:00:00Z")
    with TestClient(app) as client:
        resp = client.get("/sessions/s")
        assert resp.status_code == 200
        assert resp.json()["id"] == "s"
        assert resp.json()["status"] == "ready"
        assert client.get("/sessions/ghost").status_code == 404
