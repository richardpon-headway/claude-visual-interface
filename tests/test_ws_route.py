import json

import pytest
from fastapi.testclient import TestClient

from daemon import agent_session, reviews
from daemon.agent_session import ImageInput
from daemon.hub import hub
from daemon.main import _handle_inbound, _parse_image, app


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


async def test_inbound_ignores_malformed_and_unknown_frames():
    # Malformed/unknown frames are dropped; the socket stays open (no raise).
    await _handle_inbound("ws-bad", "{not json")
    await _handle_inbound("ws-bad", json.dumps({"type": "nope", "payload": {}}))
    await _handle_inbound("ws-bad", json.dumps({"type": "message"}))  # missing payload


async def test_inbound_message_frame_routes_to_the_agent_registry(monkeypatch):
    surface = "ws-msg"
    sent: list[tuple[str, str, object]] = []

    async def fake_send(s, text, image=None):
        sent.append((s, text, image))

    monkeypatch.setattr(agent_session.agents, "send", fake_send)

    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "hi"}}))
    # Blank / whitespace-only text with no image is ignored, not routed.
    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "  "}}))

    assert sent == [(surface, "hi", None)]


async def test_inbound_message_frame_routes_a_pasted_image(monkeypatch):
    surface = "ws-img"
    sent: list[tuple[str, str, object]] = []

    async def fake_send(s, text, image=None):
        sent.append((s, text, image))

    monkeypatch.setattr(agent_session.agents, "send", fake_send)

    async def message(text, image):
        frame = {"type": "message", "payload": {"text": text, "image": image}}
        await _handle_inbound(surface, json.dumps(frame))

    img = {"media_type": "image/png", "data": "QUJD"}
    await message("look", img)
    await message("", img)  # image with blank text still routes (image-only turn)
    await message("", {"media_type": "text/plain", "data": "QUJD"})  # malformed → dropped

    assert sent == [
        (surface, "look", ImageInput(media_type="image/png", data="QUJD")),
        (surface, "", ImageInput(media_type="image/png", data="QUJD")),
    ]


async def test_inbound_stop_frame_interrupts_the_turn_and_cancels_the_run(monkeypatch):
    surface = "ws-stop"
    called: dict[str, object] = {}

    async def fake_interrupt(s):
        called["interrupt"] = s

    def fake_cancel(s):
        called["cancel"] = s
        return True

    monkeypatch.setattr(agent_session.agents, "interrupt", fake_interrupt)
    monkeypatch.setattr(reviews, "cancel", fake_cancel)

    # No payload needed — stop applies to whatever is running on the surface.
    await _handle_inbound(surface, json.dumps({"type": "stop"}))

    assert called == {"interrupt": surface, "cancel": surface}


def test_parse_image_accepts_valid_and_fails_closed_on_malformed():
    assert _parse_image(None) is None
    assert _parse_image({"media_type": "image/png", "data": "QUJD"}) == ImageInput(
        "image/png", "QUJD"
    )
    assert _parse_image({"media_type": "text/plain", "data": "QUJD"}) is None  # not image/*
    assert _parse_image({"media_type": "image/png", "data": ""}) is None  # empty data
    assert _parse_image({"data": "QUJD"}) is None  # missing media_type
    assert _parse_image("nope") is None  # not an object
