import json

import pytest
from fastapi.testclient import TestClient

from daemon import agent_session
from daemon.hub import hub
from daemon.main import _handle_inbound, app
from daemon.view_state import store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    # The lifespan runs migrations on startup; point them at a temp DB.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def test_ws_sends_a_snapshot_on_connect_and_registers_then_cleans_up():
    surface = "ws-route"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{surface}") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert first["surface"] == surface
            assert first["payload"]["surface"] == surface
            assert hub.subscriber_count(surface) == 1

    # The connection closed, so the hub dropped the subscriber.
    assert hub.subscriber_count(surface) == 0


async def test_inbound_selection_frame_updates_the_store():
    surface = "ws-sel"
    frame = {"type": "selection", "payload": {"file": "a.py", "range": {"start": 1, "end": 3}}}
    await _handle_inbound(surface, json.dumps(frame))
    assert store.snapshot(surface)["selection"] == {
        "file": "a.py",
        "range": {"start": 1, "end": 3},
    }


async def test_inbound_ignores_malformed_unknown_and_incomplete_frames():
    surface = "ws-sel-bad"
    await _handle_inbound(surface, "{not json")
    await _handle_inbound(surface, json.dumps({"type": "nope", "payload": {}}))
    await _handle_inbound(surface, json.dumps({"type": "selection", "payload": {"file": "a.py"}}))
    assert store.snapshot(surface)["selection"] is None


async def test_inbound_message_frame_routes_to_the_agent_registry(monkeypatch):
    surface = "ws-msg"
    sent: list[tuple[str, str]] = []

    async def fake_send(s, text):
        sent.append((s, text))

    monkeypatch.setattr(agent_session.agents, "send", fake_send)

    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "hi"}}))
    # Blank / whitespace-only messages are ignored, not routed.
    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "  "}}))

    assert sent == [(surface, "hi")]
