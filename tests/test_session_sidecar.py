"""The token-monitor sidecar writer, the per-session refresh helper, and backfill."""
from __future__ import annotations

import json

import pytest

from daemon import session_sidecar, sessions
from daemon.backfill_sidecars import backfill
from daemon.db import apply_migrations_sync


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    monkeypatch.setenv("CVI_TOKEN_MONITOR_SIDECAR_DIR", str(tmp_path / "session-meta"))
    apply_migrations_sync()


def _read(sdk_session_id: str) -> dict:
    return json.loads((session_sidecar.get_sidecar_dir() / f"{sdk_session_id}.json").read_text())


def test_write_session_sidecar_writes_expected_payload():
    session_sidecar.write_session_sidecar("sdk-1", "Fix the parser")
    assert _read("sdk-1") == {
        "session_id": "sdk-1",
        "topic": "Fix the parser",
        "started_via": "cvi",
    }


def test_write_session_sidecar_swallows_oserror(tmp_path, monkeypatch):
    # Point the dir under a regular file so mkdir raises an OSError the best-effort
    # writer must swallow rather than propagate into a chat turn.
    a_file = tmp_path / "a_file"
    a_file.write_text("x")
    monkeypatch.setenv("CVI_TOKEN_MONITOR_SIDECAR_DIR", str(a_file / "nested"))
    session_sidecar.write_session_sidecar("sdk-1", "whatever")  # must not raise
    assert not (a_file / "nested").exists()


def test_update_writes_when_id_and_real_title_present():
    chat = sessions.create_chat_session("Real Title")
    sessions.set_agent_session_id(chat, "sdk-abc")
    assert session_sidecar.update_sidecar_for_session(chat) is True
    assert _read("sdk-abc")["topic"] == "Real Title"


def test_update_skips_when_no_agent_session_id():
    chat = sessions.create_chat_session("Real Title")  # no SDK id captured yet
    assert session_sidecar.update_sidecar_for_session(chat) is False


def test_update_skips_default_placeholder_title():
    chat = sessions.create_chat_session()  # title == "New chat"
    sessions.set_agent_session_id(chat, "sdk-def")
    assert session_sidecar.update_sidecar_for_session(chat) is False


def test_update_prefers_user_title_override():
    chat = sessions.create_chat_session("Auto Title")
    sessions.set_agent_session_id(chat, "sdk-ghi")
    sessions.set_user_title(chat, "Pinned Name")
    assert session_sidecar.update_sidecar_for_session(chat) is True
    assert _read("sdk-ghi")["topic"] == "Pinned Name"


def test_update_returns_false_for_unknown_surface():
    assert session_sidecar.update_sidecar_for_session("ghost") is False


def test_backfill_writes_only_eligible_sessions():
    eligible = sessions.create_chat_session("Has Title")
    sessions.set_agent_session_id(eligible, "sdk-eli")
    sessions.create_chat_session("No SDK id")  # titled but no id -> skipped
    untitled = sessions.create_chat_session()  # default title -> skipped
    sessions.set_agent_session_id(untitled, "sdk-unt")

    assert backfill() == 1
    assert _read("sdk-eli")["topic"] == "Has Title"
