"""The render primitives append a conversation segment AND push it over the hub,
plus the transient broadcast helpers (title / thinking / prompt summary)."""

import json
from typing import Any

import pytest

from daemon import messages, token_usage
from daemon.db import apply_migrations_sync
from daemon.hub import hub
from daemon.mcp_server import (
    broadcast_answer,
    broadcast_prompt_summary,
    broadcast_thinking,
    broadcast_title,
    broadcast_tokens,
    hydrate_surface,
    record_activity,
    render_html,
)
from daemon.view_state import store


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


class FakeWS:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def send_json(self, data: Any) -> None:
        self.received.append(data)


async def test_render_html_appends_an_inline_artifact_and_broadcasts():
    surface = "vc-html"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await render_html.handler({"surface": surface, "html": "<p>hi</p>", "title": "design"})
    finally:
        hub.unregister(surface, ws)

    entry = store.get_or_create(surface).activity[-1]
    assert (entry.kind, entry.text, entry.html) == ("artifact", "design", "<p>hi</p>")
    assert ws.received == [
        {
            "type": "activity",
            "surface": surface,
            "payload": {"kind": "artifact", "text": "design", "html": "<p>hi</p>"},
        }
    ]


async def test_render_html_defaults_title_to_empty():
    surface = "vc-html-notitle"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await render_html.handler({"surface": surface, "html": "<p>hi</p>"})
    finally:
        hub.unregister(surface, ws)

    entry = store.get_or_create(surface).activity[-1]
    assert (entry.kind, entry.text, entry.html) == ("artifact", "", "<p>hi</p>")


async def test_record_activity_buffers_and_broadcasts():
    surface = "vc-activity"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await record_activity(surface, "tool", "Bash")
    finally:
        hub.unregister(surface, ws)

    assert [(e.kind, e.text) for e in store.get_or_create(surface).activity] == [("tool", "Bash")]
    assert ws.received == [
        {"type": "activity", "surface": surface, "payload": {"kind": "tool", "text": "Bash"}}
    ]


async def test_record_activity_persists_the_segment_and_holds_the_row_id():
    surface = "vc-persist"
    entry = await record_activity(surface, "user", "fix the parser", html=None)

    # The row id is held on the live entry so a later summary can target it...
    assert entry.message_id is not None
    # ...and the segment is written through to SQLite, surviving a restart.
    rows = messages.list_messages(surface)
    assert [(r["id"], r["kind"], r["text"]) for r in rows] == [
        (entry.message_id, "user", "fix the parser")
    ]


async def test_snapshot_strips_the_server_only_message_id():
    surface = "vc-snapshot"
    await record_activity(surface, "text", "hello")

    snap = store.snapshot(surface)
    assert snap["activity"][0]["kind"] == "text"
    assert "message_id" not in snap["activity"][0]


async def test_hydrate_replays_persisted_history_into_the_snapshot():
    # Simulate a prior daemon run by writing transcript rows directly.
    surface = "vc-hydrate"
    messages.append_message(surface, "user", "fix the parser")
    messages.append_message(surface, "text", "on it")

    await hydrate_surface(surface)

    snap = store.snapshot(surface)
    assert [(e["kind"], e["text"]) for e in snap["activity"]] == [
        ("user", "fix the parser"),
        ("text", "on it"),
    ]
    assert "message_id" not in snap["activity"][0]


async def test_hydrate_is_idempotent_and_does_not_clobber_live_entries():
    surface = "vc-hydrate-reconnect"
    messages.append_message(surface, "user", "first")
    await hydrate_surface(surface)
    # A live entry recorded after the first connect...
    await record_activity(surface, "text", "live reply")
    # ...survives a reconnect: the second hydrate is a no-op (no re-query, no dupes).
    await hydrate_surface(surface)

    assert [(e.kind, e.text) for e in store.get_or_create(surface).activity] == [
        ("user", "first"),
        ("text", "live reply"),
    ]


async def test_hydrate_marks_empty_surfaces_so_they_are_not_requeried():
    surface = "vc-hydrate-empty"
    await hydrate_surface(surface)
    assert store.is_hydrated(surface) is True
    assert store.get_or_create(surface).activity == []


async def test_hydrate_seeds_the_session_token_total_from_persisted_usage():
    # Simulate a prior run's recorded usage; hydration must rebuild the running total.
    surface = "vc-hydrate-tokens"
    token_usage.append_usage(surface, "turn", 30, 1500)
    token_usage.append_usage(surface, "title", 5, 40)

    await hydrate_surface(surface)

    snap = store.snapshot(surface)
    assert snap["session_output_tokens"] == 35
    assert snap["session_input_tokens"] == 1540


async def test_broadcast_answer_records_the_choice_and_broadcasts():
    surface = "vc-answer"
    await record_activity(surface, "ask", "pick", ask_id="a1", questions=[])
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_answer(surface, "a1", "Chosen")
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).activity[-1].answer == "Chosen"
    assert {
        "type": "answer",
        "surface": surface,
        "payload": {"id": "a1", "answer": "Chosen"},
    } in ws.received


async def test_record_activity_persists_the_ask_payload():
    # A picker's tool-use id + questions (incl. each option's rich preview) are written
    # through as JSON so a restarted picker re-renders rich instead of falling to text.
    surface = "vc-ask-persist"
    questions = [{"question": "Which?", "options": [{"label": "A", "preview": "<h3>A</h3>"}]}]
    await record_activity(surface, "ask", "pick", ask_id="a1", questions=questions)

    row = messages.list_messages(surface)[0]
    assert json.loads(row["data"]) == {"ask_id": "a1", "questions": questions}


async def test_broadcast_answer_persists_the_choice_to_the_row():
    # The chosen value is written to the picker's row so an answered picker re-renders
    # locked after a daemon restart.
    surface = "vc-answer-persist"
    await record_activity(surface, "ask", "pick", ask_id="a1", questions=[])
    await broadcast_answer(surface, "a1", "Chosen")

    assert messages.list_messages(surface)[0]["answer"] == "Chosen"


async def test_hydrate_restores_the_ask_payload_and_answer():
    # Simulate a prior run: an ask row with its JSON payload and a recorded answer.
    surface = "vc-ask-hydrate"
    questions = [{"question": "Which?", "options": [{"label": "A", "preview": "<h3>A</h3>"}]}]
    mid = messages.append_message(
        surface, "ask", "pick", data=json.dumps({"ask_id": "a1", "questions": questions})
    )
    messages.set_message_answer(mid, "Chosen")

    await hydrate_surface(surface)

    entry = store.get_or_create(surface).activity[-1]
    assert entry.ask_id == "a1"
    assert entry.questions == questions
    assert entry.answer == "Chosen"
    # Restored payload + answer ride the connect snapshot for a reloading browser.
    snap_entry = store.snapshot(surface)["activity"][-1]
    assert snap_entry["questions"] == questions
    assert snap_entry["answer"] == "Chosen"


async def test_broadcast_tokens_accumulates_and_broadcasts_the_running_total():
    surface = "vc-tokens"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_tokens(surface, 30, 500)
        await broadcast_tokens(surface, 5, 40)
    finally:
        hub.unregister(surface, ws)

    # Each broadcast carries the new running total, not the per-call delta.
    assert ws.received == [
        {"type": "tokens", "surface": surface, "payload": {"output": 30, "input": 500}},
        {"type": "tokens", "surface": surface, "payload": {"output": 35, "input": 540}},
    ]


async def test_broadcast_title_broadcasts_without_storing():
    surface = "vc-title"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_title(surface, "Fix the parser")
    finally:
        hub.unregister(surface, ws)

    assert ws.received == [
        {"type": "title", "surface": surface, "payload": {"title": "Fix the parser"}}
    ]


async def test_broadcast_prompt_summary_broadcasts_the_index_and_text():
    surface = "vc-summary"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_prompt_summary(surface, 2, "fix the parser")
    finally:
        hub.unregister(surface, ws)

    assert ws.received == [
        {
            "type": "prompt_summary",
            "surface": surface,
            "payload": {"index": 2, "text": "fix the parser"},
        }
    ]


async def test_broadcast_thinking_sets_the_flag_and_broadcasts():
    surface = "vc-thinking"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_thinking(surface, True)
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).thinking is True
    assert ws.received == [
        {"type": "thinking", "surface": surface, "payload": {"active": True}}
    ]
