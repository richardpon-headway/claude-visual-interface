"""The runner's orchestration — status transitions + crash-safety — exercised
with a fake Agent SDK client. The real review (Claude actually calling the tools)
needs the Claude Code CLI + auth + a worktree and is verified locally."""

import asyncio
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from daemon import review_runner, sessions
from daemon.db import apply_migrations_sync, open_db
from daemon.hub import hub
from daemon.review_runner import AgentReviewRunner
from daemon.view_state import store


class FakeWS:
    """A hub subscriber that records the events broadcast to a surface."""

    def __init__(self) -> None:
        self.received: list = []

    async def send_json(self, data) -> None:
        self.received.append(data)

SESSION = "run-session"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES (?, 'review', 'running', 't', 't')",
            (SESSION,),
        )
        conn.commit()
    finally:
        conn.close()


class FakeClient:
    """Stands in for ClaudeSDKClient: an async context manager that yields canned
    messages from receive_response (or raises, to exercise the failure path)."""

    def __init__(self, *, messages=(), raise_on=None):
        self._messages = messages
        self._raise_on = raise_on
        self.queried: list[str] = []

    async def __aenter__(self):
        if self._raise_on == "enter":
            raise RuntimeError("connect failed")
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        self.queried.append(prompt)
        if self._raise_on == "query":
            raise RuntimeError("query failed")

    async def receive_response(self):
        for message in self._messages:
            yield message


def test_review_prompt_carries_session_and_base_ref():
    prompt = review_runner._review_prompt(SESSION, "main")
    assert SESSION in prompt
    assert "main" in prompt
    assert "mcp__cvi__upsert_finding" in prompt


async def test_successful_run_marks_session_ready(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="reviewing the diff"),
                ToolUseBlock(id="t1", name="mcp__cvi__upsert_finding", input={}),
            ],
            model="test",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=SESSION,
        ),
    ]
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(messages=messages)
    )

    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    assert sessions.get_session(SESSION)["status"] == "ready"


async def test_run_stores_the_agent_session_id(monkeypatch):
    messages = [
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-xyz",
        ),
    ]
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(messages=messages)
    )

    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    # Captured from the ResultMessage so chat can resume this exact conversation.
    assert sessions.get_session(SESSION)["agent_session_id"] == "sdk-xyz"


async def test_run_without_a_result_message_leaves_agent_session_id_unset(monkeypatch):
    monkeypatch.setattr(review_runner, "ClaudeSDKClient", lambda options=None: FakeClient())

    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    assert sessions.get_session(SESSION)["agent_session_id"] is None


async def test_run_resolves_the_base_ref_and_scopes_the_prompt(monkeypatch):
    async def fake_resolve(worktree_path, base_ref):
        return "origin/main"

    client = FakeClient()
    monkeypatch.setattr(review_runner, "resolve_base_ref", fake_resolve)
    monkeypatch.setattr(review_runner, "ClaudeSDKClient", lambda options=None: client)
    store.get_or_create(SESSION).activity.clear()  # the store is process-global

    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    # The diff is scoped to the resolved (fresher) ref, not the caller's stale one.
    assert "origin/main...HEAD" in client.queried[0]
    assert ("text", "scoping review to origin/main") in [
        (e.kind, e.text) for e in store.get_or_create(SESSION).activity
    ]


async def test_run_streams_activity_and_a_terminal_status_event(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="reviewing the diff"),
                ToolUseBlock(id="t1", name="Bash", input={}),
            ],
            model="test",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=SESSION,
        ),
    ]
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(messages=messages)
    )
    store.get_or_create(SESSION).activity.clear()  # the store is process-global
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")
    finally:
        hub.unregister(SESSION, ws)

    # The narration is buffered on the surface (rides a later connect snapshot),
    # led by the base-scoping line (/tmp/wt isn't a git repo, so the ref is as-is).
    assert [(e.kind, e.text) for e in store.get_or_create(SESSION).activity] == [
        ("text", "scoping review to main"),
        ("text", "reviewing the diff"),
        ("tool", "Bash"),
        ("result", "success"),
    ]
    # ...and was pushed live, capped by a terminal status event flipping the chip.
    tool_payload = {"kind": "tool", "text": "Bash"}
    assert {"type": "activity", "surface": SESSION, "payload": tool_payload} in ws.received
    assert ws.received[-1] == {"type": "status", "surface": SESSION, "payload": {"status": "ready"}}


async def test_failed_run_broadcasts_an_error_status(monkeypatch):
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(raise_on="query")
    )
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")
    finally:
        hub.unregister(SESSION, ws)

    assert ws.received[-1] == {"type": "status", "surface": SESSION, "payload": {"status": "error"}}


@pytest.mark.parametrize("raise_on", ["enter", "query"])
async def test_failed_run_marks_session_error_without_raising(monkeypatch, raise_on):
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(raise_on=raise_on)
    )

    # Must not propagate — the run is a fire-and-forget background task.
    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    assert sessions.get_session(SESSION)["status"] == "error"


async def test_cancelled_run_marks_session_stopped(monkeypatch):
    started = asyncio.Event()

    class BlockingClient(FakeClient):
        async def receive_response(self):
            started.set()
            await asyncio.Event().wait()  # block mid-run until cancelled
            yield  # pragma: no cover

    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: BlockingClient()
    )
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        task = asyncio.create_task(
            AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")
        )
        await asyncio.wait_for(started.wait(), 1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        hub.unregister(SESSION, ws)

    # Stop lands on a distinct terminal state, not 'error' (it was deliberate).
    assert sessions.get_session(SESSION)["status"] == "stopped"
    assert ws.received[-1] == {
        "type": "status",
        "surface": SESSION,
        "payload": {"status": "stopped"},
    }


def _seed(session_id, *findings):
    """Insert a session + its findings. Each finding is (id, file, created_at, anchor|None)."""
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES (?, 'review', 'running', 't', 't')",
            (session_id,),
        )
        for fid, file, created_at, anchor in findings:
            conn.execute(
                "INSERT INTO finding "
                "(id, session_id, file, anchor, title, body, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 't', 'b', ?, ?)",
                (
                    fid,
                    session_id,
                    file,
                    json.dumps(anchor) if anchor else None,
                    created_at,
                    created_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


async def test_run_auto_opens_the_oldest_findings_file(monkeypatch):
    sid = "auto-open"
    anchor = {"snippet": "x", "range": {"start": 10, "end": 12}}
    _seed(
        sid,
        ("f-old", "old.py", "2026-01-01T00:00:00Z", anchor),
        ("f-new", "new.py", "2026-02-01T00:00:00Z", None),
    )
    monkeypatch.setattr(review_runner, "ClaudeSDKClient", lambda options=None: FakeClient())

    await AgentReviewRunner().run(session_id=sid, worktree_path="/tmp/wt", base_ref="main")

    snap = store.snapshot(sid)
    assert snap["open"][0]["file"] == "old.py"  # oldest finding; pane key is int
    assert snap["open"][0]["range"] == {"start": 10, "end": 12}
    assert sessions.get_session(sid)["status"] == "ready"


async def test_run_with_no_findings_opens_nothing(monkeypatch):
    sid = "auto-open-empty"
    _seed(sid)
    monkeypatch.setattr(review_runner, "ClaudeSDKClient", lambda options=None: FakeClient())

    await AgentReviewRunner().run(session_id=sid, worktree_path="/tmp/wt", base_ref="main")

    assert store.snapshot(sid)["open"] == {}
    assert sessions.get_session(sid)["status"] == "ready"


async def test_auto_open_failure_leaves_review_ready(monkeypatch):
    sid = "auto-open-fail"
    _seed(sid, ("f1", "a.py", "2026-01-01T00:00:00Z", None))

    async def boom(*args, **kwargs):
        raise RuntimeError("open blew up")

    monkeypatch.setattr(review_runner, "open_file_on_surface", boom)
    monkeypatch.setattr(review_runner, "ClaudeSDKClient", lambda options=None: FakeClient())

    await AgentReviewRunner().run(session_id=sid, worktree_path="/tmp/wt", base_ref="main")

    assert sessions.get_session(sid)["status"] == "ready"  # auto-open failure is swallowed
