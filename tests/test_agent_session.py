"""The conversational session: lazy start, turn serialization, idle/shutdown reaping,
and the no-worktree guard — exercised with a fake Agent SDK client. The real agent
turn (Claude actually answering) needs the CLI + auth and is verified locally."""

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from daemon import agent_session
from daemon.agent_session import AgentSessionRegistry
from daemon.db import apply_migrations_sync, open_db
from daemon.view_state import store

SESSION = "chat-session"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


def _seed_session(session_id, *, worktree_path, session_type="review", agent_session_id=None):
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session "
            "(id, type, status, worktree_path, agent_session_id, created_at, updated_at) "
            "VALUES (?, ?, 'ready', ?, ?, 't', 't')",
            (session_id, session_type, worktree_path, agent_session_id),
        )
        conn.commit()
    finally:
        conn.close()


class FakeClient:
    """An async-ctx-manager stand-in for ClaudeSDKClient that records queries and
    replies with a canned assistant message + result per turn."""

    instances: list["FakeClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.queried: list[str] = []
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        # A string is the text-only fast path; a multimodal turn arrives as an async
        # iterable of message dicts — drain it so the test can inspect the blocks.
        if isinstance(prompt, str):
            self.queried.append(prompt)
        else:
            async for msg in prompt:
                self.queried.append(msg)

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text="on it")], model="test")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=SESSION,
        )


async def _wait_until(predicate, limit=1.0):
    elapsed = 0.0
    while elapsed < limit:
        if predicate():
            return
        await asyncio.sleep(0.01)
        elapsed += 0.01
    raise AssertionError("condition not met within limit")


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(agent_session, "ClaudeSDKClient", lambda options=None: FakeClient(options))


async def test_first_message_starts_a_session_records_user_and_relays_reply():
    _seed_session(SESSION, worktree_path="/tmp/wt")
    store.get_or_create(SESSION).activity.clear()
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "review the diff")
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create(SESSION).activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]
    assert ("user", "review the diff") in kinds
    assert ("text", "on it") in kinds
    assert ("result", "success") in kinds
    assert FakeClient.instances[0].queried == ["review the diff"]

    await reg.shutdown_all()


async def test_turns_are_serialized_in_order():
    _seed_session(SESSION, worktree_path="/tmp/wt")
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "first")
    await reg.send(SESSION, "second")
    await _wait_until(
        lambda: len(FakeClient.instances) == 1
        and FakeClient.instances[0].queried == ["first", "second"]
    )

    # One session, one client — the second turn ran after the first completed.
    assert len(FakeClient.instances) == 1
    await reg.shutdown_all()


async def test_idle_timeout_closes_and_deregisters(monkeypatch):
    _seed_session(SESSION, worktree_path="/tmp/wt")
    monkeypatch.setattr(agent_session, "AGENT_IDLE_SECONDS", 0.05)
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hi")
    await _wait_until(lambda: reg.active_surfaces() == [])


async def test_shutdown_all_closes_a_live_session():
    _seed_session(SESSION, worktree_path="/tmp/wt")
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hi")
    await _wait_until(lambda: reg.active_surfaces() == [SESSION])

    await reg.shutdown_all()
    assert reg.active_surfaces() == []


async def test_chat_session_with_no_worktree_starts_and_chats():
    # A general chat has no worktree — it starts anyway and runs with cwd=None.
    _seed_session("chat-no-wt", worktree_path=None, session_type="chat")
    store.get_or_create("chat-no-wt").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send("chat-no-wt", "make me a dashboard")
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("chat-no-wt").activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create("chat-no-wt").activity]
    assert ("user", "make me a dashboard") in kinds
    assert ("text", "on it") in kinds
    assert FakeClient.instances[0].options.cwd is None
    await reg.shutdown_all()


async def test_image_turn_sends_an_image_block_and_marks_the_feed():
    _seed_session("img", worktree_path=None, session_type="chat")
    store.get_or_create("img").activity.clear()
    reg = AgentSessionRegistry()

    image = agent_session.ImageInput(media_type="image/png", data="QUJD")
    await reg.send("img", "what is this?", image=image)
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("img").activity)
    )

    # The query carried a single multimodal user message with text + image blocks.
    sent = FakeClient.instances[0].queried
    assert len(sent) == 1
    blocks = sent[0]["message"]["content"]
    assert {"type": "text", "text": "what is this?"} in blocks
    image_block = next(b for b in blocks if b["type"] == "image")
    assert image_block["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}

    # The feed marks the image without dumping base64.
    kinds = [(e.kind, e.text) for e in store.get_or_create("img").activity]
    assert ("user", "[image] what is this?") in kinds
    assert "QUJD" not in str(kinds)
    await reg.shutdown_all()


async def test_image_only_turn_marks_the_feed_and_sends_just_the_image():
    _seed_session("img2", worktree_path=None, session_type="chat")
    store.get_or_create("img2").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send("img2", "", image=agent_session.ImageInput(media_type="image/png", data="QUJD"))
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("img2").activity)
    )

    blocks = FakeClient.instances[0].queried[0]["message"]["content"]
    assert [b["type"] for b in blocks] == ["image"]  # no empty text block
    kinds = [(e.kind, e.text) for e in store.get_or_create("img2").activity]
    assert ("user", "[image]") in kinds
    await reg.shutdown_all()


async def test_unknown_surface_records_a_notice_and_starts_nothing():
    # No session row at all — the one thing that genuinely can't chat.
    store.get_or_create("ghost").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send("ghost", "hello?")

    assert reg.active_surfaces() == []
    notes = [e.text for e in store.get_or_create("ghost").activity]
    assert any("no session" in n for n in notes)
    assert FakeClient.instances == []


async def test_turn_sets_thinking_during_and_clears_after(monkeypatch):
    _seed_session("think", worktree_path=None, session_type="chat")
    seen: dict[str, bool] = {}

    class ThinkingProbeClient(FakeClient):
        async def query(self, prompt):
            seen["during"] = store.get_or_create("think").thinking
            await super().query(prompt)

    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: ThinkingProbeClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send("think", "hi")
    # Wait until the turn started (during recorded) AND the finally cleared the flag.
    await _wait_until(
        lambda: "during" in seen and store.get_or_create("think").thinking is False
    )

    assert seen["during"] is True  # thinking was on while the turn ran
    assert store.get_or_create("think").thinking is False  # cleared after
    await reg.shutdown_all()


async def test_thinking_clears_when_a_turn_errors(monkeypatch):
    _seed_session("think-err", worktree_path=None, session_type="chat")

    class BoomClient(FakeClient):
        async def query(self, prompt):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: BoomClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send("think-err", "hi")
    await _wait_until(
        lambda: any("turn error" in e.text for e in store.get_or_create("think-err").activity)
        and store.get_or_create("think-err").thinking is False
    )

    assert store.get_or_create("think-err").thinking is False
    await reg.shutdown_all()


class FlakyClient(FakeClient):
    """Fails the first ``fail_times`` attempts with a transient API-error result
    (no content streamed), then replies normally — stands in for a momentary 529."""

    def __init__(self, options=None, fail_times=1, status=529):
        super().__init__(options)
        self._remaining_failures = fail_times
        self._status = status

    async def receive_response(self):
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            yield ResultMessage(
                subtype="success",  # the CLI reports api errors with subtype "success"
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id=SESSION,
                api_error_status=self._status,
            )
            return
        async for message in super().receive_response():
            yield message


async def test_transient_api_error_is_retried_then_succeeds(monkeypatch):
    _seed_session("flaky", worktree_path=None, session_type="chat")
    store.get_or_create("flaky").activity.clear()
    monkeypatch.setattr(agent_session, "_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(agent_session, "_RETRY_MAX_DELAY", 0.0)
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: FlakyClient(options, fail_times=1)
    )
    reg = AgentSessionRegistry()

    await reg.send("flaky", "hi")
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("flaky").activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create("flaky").activity]
    # The 529 was swallowed; the user sees only the eventual success.
    assert ("text", "on it") in kinds
    assert ("result", "success") in kinds
    assert not any("API error" in text for _, text in kinds)
    # The turn was re-queried after the transient failure.
    assert FakeClient.instances[0].queried == ["hi", "hi"]
    await reg.shutdown_all()


async def test_transient_api_error_surfaced_after_retries_exhausted(monkeypatch):
    _seed_session("downed", worktree_path=None, session_type="chat")
    store.get_or_create("downed").activity.clear()
    monkeypatch.setattr(agent_session, "_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(agent_session, "_RETRY_MAX_DELAY", 0.0)
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: FlakyClient(options, fail_times=99)
    )
    reg = AgentSessionRegistry()

    await reg.send("downed", "hi")
    await _wait_until(
        lambda: any("API error" in e.text for e in store.get_or_create("downed").activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create("downed").activity]
    assert ("result", "API error 529") in kinds
    # Tried exactly _MAX_TURN_ATTEMPTS times, then gave up.
    assert FakeClient.instances[0].queried == ["hi"] * agent_session._MAX_TURN_ATTEMPTS
    assert store.get_or_create("downed").thinking is False
    await reg.shutdown_all()


async def test_transient_error_after_content_streamed_is_not_retried(monkeypatch):
    # Once content has streamed, a retry would duplicate it — so surface the error
    # instead of re-running.
    _seed_session("mid", worktree_path=None, session_type="chat")
    store.get_or_create("mid").activity.clear()

    class MidStreamErrorClient(FakeClient):
        async def receive_response(self):
            yield AssistantMessage(content=[TextBlock(text="partial")], model="test")
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id=SESSION,
                api_error_status=529,
            )

    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: MidStreamErrorClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send("mid", "hi")
    await _wait_until(
        lambda: any("API error" in e.text for e in store.get_or_create("mid").activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create("mid").activity]
    assert ("text", "partial") in kinds
    assert ("result", "API error 529") in kinds
    assert FakeClient.instances[0].queried == ["hi"]  # not re-queried
    await reg.shutdown_all()


async def test_chat_session_uses_the_general_prompt_with_its_surface_id():
    _seed_session("chat-p", worktree_path=None, session_type="chat")
    reg = AgentSessionRegistry()

    await reg.send("chat-p", "hi")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    prompt = FakeClient.instances[0].options.system_prompt
    assert prompt.startswith(agent_session.CVI_CHAT_SYSTEM_PROMPT)
    assert "chat-p" in prompt  # the agent is told the surface to render to
    await reg.shutdown_all()


async def test_review_session_uses_the_review_prompt_with_its_surface_id():
    _seed_session("review-p", worktree_path="/tmp/wt", session_type="review")
    reg = AgentSessionRegistry()

    await reg.send("review-p", "why is finding 1 low?")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    prompt = FakeClient.instances[0].options.system_prompt
    assert prompt.startswith(agent_session.CVI_REVIEW_SYSTEM_PROMPT)
    assert "review-p" in prompt
    await reg.shutdown_all()


def test_with_surface_id_appends_the_id_and_instruction():
    out = agent_session.with_surface_id("BASE PROMPT", "surface-123")
    assert out.startswith("BASE PROMPT")
    assert "surface-123" in out
    assert "every cvi tool" in out
    assert "default" in out  # explicitly warns the agent off guessing "default"


async def test_resumes_the_recorded_review_session():
    _seed_session(SESSION, worktree_path="/tmp/wt", agent_session_id="sdk-xyz")
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "why is finding 1 low?")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    # The chat client continues the review's conversation.
    assert FakeClient.instances[0].options.resume == "sdk-xyz"
    await reg.shutdown_all()


async def test_starts_fresh_when_no_review_session_recorded():
    _seed_session(SESSION, worktree_path="/tmp/wt")  # agent_session_id is NULL
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hello")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    assert FakeClient.instances[0].options.resume is None
    await reg.shutdown_all()


async def test_falls_back_to_fresh_when_resume_fails(monkeypatch):
    _seed_session(SESSION, worktree_path="/tmp/wt", agent_session_id="stale-id")
    store.get_or_create(SESSION).activity.clear()

    class ResumeFailClient(FakeClient):
        async def __aenter__(self):
            if self.options is not None and self.options.resume is not None:
                raise RuntimeError("no such session to resume")
            return self

    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: ResumeFailClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "still works?")
    # The fresh retry (resume=None) serves the queued message.
    await _wait_until(
        lambda: any(c.options.resume is None and c.queried for c in FakeClient.instances)
    )

    notes = [e.text for e in store.get_or_create(SESSION).activity]
    assert any("could not resume" in n for n in notes)
    await reg.shutdown_all()
