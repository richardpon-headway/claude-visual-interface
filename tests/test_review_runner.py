"""The runner's orchestration — status transitions + crash-safety — exercised
with a fake Agent SDK client. The real review (Claude actually calling the tools)
needs the Claude Code CLI + auth + a worktree and is verified locally."""

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from daemon import review_runner, sessions
from daemon.db import apply_migrations_sync, open_db
from daemon.review_runner import AgentReviewRunner

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

    async def __aenter__(self):
        if self._raise_on == "enter":
            raise RuntimeError("connect failed")
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
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


@pytest.mark.parametrize("raise_on", ["enter", "query"])
async def test_failed_run_marks_session_error_without_raising(monkeypatch, raise_on):
    monkeypatch.setattr(
        review_runner, "ClaudeSDKClient", lambda options=None: FakeClient(raise_on=raise_on)
    )

    # Must not propagate — the run is a fire-and-forget background task.
    await AgentReviewRunner().run(session_id=SESSION, worktree_path="/tmp/wt", base_ref="main")

    assert sessions.get_session(SESSION)["status"] == "error"
