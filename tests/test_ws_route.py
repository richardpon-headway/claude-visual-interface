import json

import pytest
from fastapi.testclient import TestClient

from daemon import agent_session
from daemon.agent_session import ImageInput
from daemon.hub import hub
from daemon.main import _handle_inbound, _parse_image, _parse_images, app


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

    async def fake_send(s, text, images=None):
        sent.append((s, text, images))

    monkeypatch.setattr(agent_session.agents, "send", fake_send)

    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "hi"}}))
    # Blank / whitespace-only text with no image is ignored, not routed.
    await _handle_inbound(surface, json.dumps({"type": "message", "payload": {"text": "  "}}))

    assert sent == [(surface, "hi", [])]


async def test_inbound_message_frame_routes_pasted_images(monkeypatch):
    surface = "ws-img"
    sent: list[tuple[str, str, object]] = []

    async def fake_send(s, text, images=None):
        sent.append((s, text, images))

    monkeypatch.setattr(agent_session.agents, "send", fake_send)

    async def message(payload):
        await _handle_inbound(surface, json.dumps({"type": "message", "payload": payload}))

    png = {"media_type": "image/png", "data": "QUJD"}
    jpg = {"media_type": "image/jpeg", "data": "WFla"}
    bad = {"media_type": "text/plain", "data": "QUJD"}

    await message({"text": "look", "images": [png, jpg]})  # both kept, in order
    await message({"text": "", "images": [png]})  # image-only turn still routes
    await message({"text": "x", "images": [png, bad]})  # malformed entry dropped
    await message({"text": "y", "images": []})  # empty list + text → text-only
    # Legacy single `image` key still routes one image (old front-end compat).
    await message({"text": "legacy", "image": png})

    assert sent == [
        (surface, "look", [ImageInput("image/png", "QUJD"), ImageInput("image/jpeg", "WFla")]),
        (surface, "", [ImageInput("image/png", "QUJD")]),
        (surface, "x", [ImageInput("image/png", "QUJD")]),
        (surface, "y", []),
        (surface, "legacy", [ImageInput("image/png", "QUJD")]),
    ]


async def test_inbound_answer_frame_routes_to_the_agent_registry(monkeypatch):
    surface = "ws-answer"
    answered: list[tuple[str, str, str]] = []

    async def fake_answer(s, ask_id, answer):
        answered.append((s, ask_id, answer))

    monkeypatch.setattr(agent_session.agents, "answer", fake_answer)

    await _handle_inbound(
        surface, json.dumps({"type": "answer", "payload": {"id": "a1", "answer": "Custom modal"}})
    )
    # Missing id / blank answer is ignored, not routed.
    await _handle_inbound(surface, json.dumps({"type": "answer", "payload": {"answer": "x"}}))
    await _handle_inbound(
        surface, json.dumps({"type": "answer", "payload": {"id": "a2", "answer": ""}})
    )

    assert answered == [(surface, "a1", "Custom modal")]


async def test_inbound_stop_frame_interrupts_the_turn(monkeypatch):
    surface = "ws-stop"
    called: dict[str, object] = {}

    async def fake_interrupt(s):
        called["interrupt"] = s

    monkeypatch.setattr(agent_session.agents, "interrupt", fake_interrupt)

    # No payload needed — stop applies to whatever is running on the surface.
    await _handle_inbound(surface, json.dumps({"type": "stop"}))

    assert called == {"interrupt": surface}


def test_parse_image_accepts_valid_and_fails_closed_on_malformed():
    assert _parse_image(None) is None
    assert _parse_image({"media_type": "image/png", "data": "QUJD"}) == ImageInput(
        "image/png", "QUJD"
    )
    assert _parse_image({"media_type": "text/plain", "data": "QUJD"}) is None  # not image/*
    assert _parse_image({"media_type": "image/png", "data": ""}) is None  # empty data
    assert _parse_image({"data": "QUJD"}) is None  # missing media_type
    assert _parse_image("nope") is None  # not an object


def test_parse_images_validates_a_list_and_caps_at_eight():
    png = {"media_type": "image/png", "data": "QUJD"}
    bad = {"media_type": "text/plain", "data": "QUJD"}

    assert _parse_images(None) == []  # absent
    assert _parse_images("nope") == []  # not a list
    # A valid list keeps every image, in order.
    assert _parse_images([png, png]) == [ImageInput("image/png", "QUJD")] * 2
    # A mixed list drops only the malformed entries.
    assert _parse_images([png, bad, png]) == [ImageInput("image/png", "QUJD")] * 2
    # An over-cap list is truncated to the per-turn maximum.
    assert _parse_images([png] * 12) == [ImageInput("image/png", "QUJD")] * 8
