"""The render primitives append a conversation segment AND push it over the hub,
plus the transient broadcast helpers (status / title / thinking / prompt summary)."""

from typing import Any

from daemon import mcp_server
from daemon.hub import hub
from daemon.mcp_server import (
    broadcast_prompt_summary,
    broadcast_status,
    broadcast_thinking,
    broadcast_title,
    record_activity,
    render_file,
    render_html,
)
from daemon.view_state import store


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

    assert ws.received == [{"type": "status", "surface": surface, "payload": {"status": "ready"}}]


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
