"""The view-control primitives mutate the live store AND push over the hub."""

import json
from typing import Any

from daemon import mcp_server
from daemon.hub import hub
from daemon.mcp_server import (
    broadcast_prompt_summary,
    broadcast_status,
    broadcast_thinking,
    broadcast_title,
    get_selection,
    get_view_state,
    highlight_range,
    open_code,
    record_activity,
    render_file,
    render_html,
    show_diff,
    split_pane,
)
from daemon.view_state import store


class FakeWS:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def send_json(self, data: Any) -> None:
        self.received.append(data)


async def test_open_code_updates_store_and_broadcasts():
    surface = "vc-open"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await open_code.handler(
            {"surface": surface, "file": "a.py", "range": {"start": 1, "end": 4}, "pane": 0}
        )
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).open[0].file == "a.py"
    assert ws.received == [
        {
            "type": "open_code",
            "surface": surface,
            "payload": {"file": "a.py", "range": {"start": 1, "end": 4}, "pane": 0},
        }
    ]


async def test_split_pane_broadcasts_event():
    surface = "vc-split"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await split_pane.handler({"surface": surface, "n": 3})
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).panes == 3
    assert ws.received == [{"type": "split_pane", "surface": surface, "payload": {"n": 3}}]


async def test_highlight_range_broadcasts_event():
    surface = "vc-highlight"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await highlight_range.handler(
            {"surface": surface, "file": "a.py", "range": {"start": 7, "end": 9}}
        )
    finally:
        hub.unregister(surface, ws)

    assert ws.received[0]["type"] == "highlight_range"
    assert ws.received[0]["payload"] == {"file": "a.py", "range": {"start": 7, "end": 9}}


async def test_show_diff_broadcasts_event():
    surface = "vc-diff"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await show_diff.handler({"surface": surface, "a": "current", "b": "patch-1"})
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).diff.a == "current"
    assert ws.received == [
        {"type": "show_diff", "surface": surface, "payload": {"a": "current", "b": "patch-1"}}
    ]


async def test_render_html_appends_an_inline_artifact_and_broadcasts():
    surface = "vc-html"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await render_html.handler(
            {"surface": surface, "html": "<p>hi</p>", "title": "design"}
        )
    finally:
        hub.unregister(surface, ws)

    # render_html now appends an inline artifact segment to the conversation stream.
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


async def test_render_file_appends_a_diff_segment_and_broadcasts(monkeypatch):
    surface = "vc-file"
    monkeypatch.setattr(
        mcp_server.sessions,
        "get_session",
        lambda sid: {"worktree_path": "/tmp/wt", "base_ref": "main"},
    )

    async def fake_resolve(wt, base):
        return base

    async def fake_diff(wt, base, path):
        return "@@ -1 +1 @@\n-a\n+b"

    monkeypatch.setattr(mcp_server, "resolve_base_ref", fake_resolve)
    monkeypatch.setattr(mcp_server, "file_diff", fake_diff)

    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await render_file.handler({"surface": surface, "path": "a.py"})
    finally:
        hub.unregister(surface, ws)

    entry = store.get_or_create(surface).activity[-1]
    assert (entry.kind, entry.text, entry.diff) == ("file", "a.py", "@@ -1 +1 @@\n-a\n+b")
    assert ws.received[-1]["payload"] == {
        "kind": "file",
        "text": "a.py",
        "diff": "@@ -1 +1 @@\n-a\n+b",
    }


async def test_render_file_errors_without_a_worktree(monkeypatch):
    monkeypatch.setattr(mcp_server.sessions, "get_session", lambda sid: {"worktree_path": None})
    result = await render_file.handler({"surface": "vc-file-nw", "path": "a.py"})
    assert result.get("is_error") is True


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


async def test_broadcast_status_broadcasts_without_storing():
    surface = "vc-status"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await broadcast_status(surface, "ready")
    finally:
        hub.unregister(surface, ws)

    assert ws.received == [
        {"type": "status", "surface": surface, "payload": {"status": "ready"}}
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


async def test_get_view_state_returns_current_state():
    surface = "pull-vs"
    await split_pane.handler({"surface": surface, "n": 2})
    result = await get_view_state.handler({"surface": surface})
    data = json.loads(result["content"][0]["text"])
    assert data["surface"] == surface
    assert data["panes"] == 2


async def test_get_selection_reflects_stored_selection():
    surface = "pull-sel"
    store.set_selection(surface, "a.py", {"start": 2, "end": 5})
    result = await get_selection.handler({"surface": surface})
    data = json.loads(result["content"][0]["text"])
    assert data["selection"] == {"file": "a.py", "range": {"start": 2, "end": 5}}
