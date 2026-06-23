"""The conversational session: lazy start, turn serialization, idle/shutdown reaping,
and resume — exercised with a fake Agent SDK client. The real agent turn (Claude
actually answering) needs the CLI + auth and is verified locally."""

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from daemon import agent_session, config, messages, sessions, titles, token_usage
from daemon.agent_session import AgentSessionRegistry
from daemon.db import apply_migrations_sync, open_db
from daemon.hub import hub
from daemon.view_state import store


class FakeWS:
    """A hub subscriber that records the events broadcast to a surface."""

    def __init__(self) -> None:
        self.received: list = []

    async def send_json(self, data) -> None:
        self.received.append(data)


class _NoTitleGen:
    """The default titling generator in tests: never produces a title, so existing
    tests incur no title side-effects and open no second SDK client."""

    async def generate(self, message):
        return titles.TitleResult(None)

SESSION = "chat-session"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


def _seed_session(session_id, *, session_type="chat", agent_session_id=None):
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session "
            "(id, type, status, agent_session_id, created_at, updated_at) "
            "VALUES (?, ?, 'ready', ?, 't', 't')",
            (session_id, session_type, agent_session_id),
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
    # Neutralize auto-titling and prompt-summaries by default; tests that exercise
    # them inject their own generator/summarizer.
    monkeypatch.setattr(titles, "generator", _NoTitleGen())
    monkeypatch.setattr(titles, "summarizer", _NoTitleGen())


async def test_first_message_starts_a_session_records_user_and_relays_reply():
    _seed_session(SESSION)
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
    _seed_session(SESSION)
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


async def test_user_turn_is_recorded_at_execution_time_not_on_enqueue(monkeypatch):
    # A message sent while a prior turn is still streaming must not jump ahead of
    # that turn's answer — the transcript pairs each prompt with its own reply.
    _seed_session(SESSION, session_type="chat")
    store.get_or_create(SESSION).activity.clear()
    release = asyncio.Event()

    class GatedClient(FakeClient):
        async def receive_response(self):
            last = self.queried[-1]
            yield AssistantMessage(content=[TextBlock(text=f"answer to {last}")], model="test")
            if last == "first":
                await release.wait()  # hold the first turn open so a 2nd can queue
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=SESSION,
            )

    monkeypatch.setattr(agent_session, "ClaudeSDKClient", lambda options=None: GatedClient(options))
    reg = AgentSessionRegistry()

    def kinds():
        return [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]

    await reg.send(SESSION, "first")
    await _wait_until(lambda: ("text", "answer to first") in kinds())
    # The second message is enqueued mid-turn — its YOU line must not appear yet.
    await reg.send(SESSION, "second")
    assert ("user", "second") not in kinds()

    release.set()
    await _wait_until(lambda: kinds().count(("result", "success")) == 2)
    assert kinds() == [
        ("user", "first"),
        ("text", "answer to first"),
        ("result", "success"),
        ("user", "second"),
        ("text", "answer to second"),
        ("result", "success"),
    ]
    await reg.shutdown_all()


async def test_idle_timeout_closes_and_deregisters(monkeypatch):
    _seed_session(SESSION)
    monkeypatch.setattr(agent_session, "AGENT_IDLE_SECONDS", 0.05)
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hi")
    await _wait_until(lambda: reg.active_surfaces() == [])


async def test_shutdown_all_closes_a_live_session():
    _seed_session(SESSION)
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hi")
    await _wait_until(lambda: reg.active_surfaces() == [SESSION])

    await reg.shutdown_all()
    assert reg.active_surfaces() == []


async def test_chat_session_starts_and_chats():
    # A session with a row starts on first message and runs a turn end to end.
    _seed_session("chat-no-wt", session_type="chat")
    store.get_or_create("chat-no-wt").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send("chat-no-wt", "make me a dashboard")
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("chat-no-wt").activity)
    )

    kinds = [(e.kind, e.text) for e in store.get_or_create("chat-no-wt").activity]
    assert ("user", "make me a dashboard") in kinds
    assert ("text", "on it") in kinds
    assert FakeClient.instances[0].options.cwd == str(config.get_working_dir())
    await reg.shutdown_all()


async def test_chat_session_uses_configured_working_dir(tmp_path, monkeypatch):
    # The configured working_dir is threaded through to the SDK client's cwd.
    workdir = tmp_path / "code"
    workdir.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"working_dir: {workdir}\n")
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))

    _seed_session("chat-wd", session_type="chat")
    store.get_or_create("chat-wd").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send("chat-wd", "hi")
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("chat-wd").activity)
    )

    assert FakeClient.instances[0].options.cwd == str(workdir)
    await reg.shutdown_all()


async def test_image_turn_sends_an_image_block_and_marks_the_feed():
    _seed_session("img", session_type="chat")
    store.get_or_create("img").activity.clear()
    reg = AgentSessionRegistry()

    image = agent_session.ImageInput(media_type="image/png", data="QUJD")
    await reg.send("img", "what is this?", images=[image])
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


async def test_multi_image_turn_sends_each_block_in_order_and_marks_the_count():
    _seed_session("imgs", session_type="chat")
    store.get_or_create("imgs").activity.clear()
    reg = AgentSessionRegistry()

    images = [
        agent_session.ImageInput(media_type="image/png", data="QUJD"),
        agent_session.ImageInput(media_type="image/jpeg", data="WFla"),
    ]
    await reg.send("imgs", "compare these", images=images)
    await _wait_until(
        lambda: any(e.kind == "result" for e in store.get_or_create("imgs").activity)
    )

    # One multimodal message carrying the text then both images, in order.
    sent = FakeClient.instances[0].queried
    assert len(sent) == 1
    blocks = sent[0]["message"]["content"]
    assert [b["type"] for b in blocks] == ["text", "image", "image"]
    assert [b["source"] for b in blocks[1:]] == [
        {"type": "base64", "media_type": "image/png", "data": "QUJD"},
        {"type": "base64", "media_type": "image/jpeg", "data": "WFla"},
    ]

    # The feed marks the count, not the bytes.
    kinds = [(e.kind, e.text) for e in store.get_or_create("imgs").activity]
    assert ("user", "[2 images] compare these") in kinds
    assert "QUJD" not in str(kinds)
    await reg.shutdown_all()


async def test_image_only_turn_marks_the_feed_and_sends_just_the_image():
    _seed_session("img2", session_type="chat")
    store.get_or_create("img2").activity.clear()
    reg = AgentSessionRegistry()

    await reg.send(
        "img2", "", images=[agent_session.ImageInput(media_type="image/png", data="QUJD")]
    )
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
    _seed_session("think", session_type="chat")
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
    _seed_session("think-err", session_type="chat")

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
    _seed_session("flaky", session_type="chat")
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
    _seed_session("downed", session_type="chat")
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
    _seed_session("mid", session_type="chat")
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


class BlockingClient(FakeClient):
    """Streams one assistant message, then blocks mid-turn until interrupted —
    interrupt() unblocks it with a (suppressed) terminal abort result."""

    def __init__(self, options=None):
        super().__init__(options)
        self.released = asyncio.Event()
        self.interrupt_called = False

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text="working")], model="test")
        await self.released.wait()
        yield ResultMessage(
            subtype="error_during_execution",
            duration_ms=1,
            duration_api_ms=1,
            is_error=True,
            num_turns=1,
            session_id=SESSION,
        )

    async def interrupt(self):
        self.interrupt_called = True
        self.released.set()


async def test_interrupt_stops_the_turn_and_keeps_the_session_open(monkeypatch):
    _seed_session(SESSION, session_type="chat")
    store.get_or_create(SESSION).activity.clear()
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: BlockingClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "long task")
    # Wait until the turn is in flight (thinking on, first message relayed).
    await _wait_until(lambda: store.get_or_create(SESSION).thinking is True)

    await reg.interrupt(SESSION)
    await _wait_until(lambda: store.get_or_create(SESSION).thinking is False)

    client = FakeClient.instances[0]
    assert isinstance(client, BlockingClient)
    assert client.interrupt_called is True
    kinds = [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]
    assert ("text", "working") in kinds
    assert ("result", "stopped") in kinds
    # The aborted turn's own terminal result is suppressed, not relayed.
    assert not any(text == "error_during_execution" for _, text in kinds)
    # The session stays open for the next message.
    assert reg.active_surfaces() == [SESSION]
    await reg.shutdown_all()


async def test_interrupt_is_a_noop_when_no_turn_is_running():
    # Nothing started for the surface — interrupt must not raise or start anything.
    reg = AgentSessionRegistry()
    await reg.interrupt("idle-surface")
    assert reg.active_surfaces() == []


class SharedStreamClient(FakeClient):
    """Models the SDK's single shared transport stream across turns. receive_response()
    drains a per-client queue and (like the real wrapper) ends after the first
    ResultMessage. A mid-turn interrupt() pushes a trailing chunk *and then* the terminal
    abort onto that shared stream — so a turn that abandons its receive loop on the
    trailing chunk leaves the abort buffered, where the NEXT turn's receive_response()
    picks it up. This is the real shape BlockingClient doesn't capture."""

    def __init__(self, options=None):
        super().__init__(options)
        self._stream: asyncio.Queue = asyncio.Queue()
        self.interrupt_called = False

    async def query(self, prompt):
        await super().query(prompt)
        text = self.queried[-1]
        if text == "first":
            # Stream one chunk, then leave the turn in flight (no terminal) so it
            # blocks until interrupted.
            self._stream.put_nowait(
                AssistantMessage(content=[TextBlock(text="working")], model="test")
            )
        else:
            self._stream.put_nowait(
                AssistantMessage(content=[TextBlock(text=f"answer to {text}")], model="test")
            )
            self._stream.put_nowait(
                ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id=SESSION,
                )
            )

    async def receive_response(self):
        while True:
            msg = await self._stream.get()
            yield msg
            if isinstance(msg, ResultMessage):
                return

    async def interrupt(self):
        self.interrupt_called = True
        # The SDK keeps streaming after the interrupt signal: a trailing chunk, then the
        # terminal abort — both land on the shared stream the loop is reading.
        self._stream.put_nowait(
            AssistantMessage(content=[TextBlock(text="trailing")], model="test")
        )
        self._stream.put_nowait(
            ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id=SESSION,
            )
        )


async def test_interrupt_then_next_prompt_does_not_leak_or_desync(monkeypatch):
    # Stop a turn mid-flight, then immediately send another. The interrupted turn's
    # terminal abort must be drained within that turn — not leak into the next turn's
    # shared stream, where it would attach to the wrong prompt and shift every later
    # reply down one. Fails on the pre-fix early-return (abort relayed under "second",
    # its real reply pushed to a turn that never comes).
    _seed_session(SESSION, session_type="chat")
    store.get_or_create(SESSION).activity.clear()
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: SharedStreamClient(options)
    )
    reg = AgentSessionRegistry()

    def kinds():
        return [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]

    await reg.send(SESSION, "first")
    await _wait_until(lambda: ("text", "working") in kinds())  # turn 1 in flight

    await reg.interrupt(SESSION)
    await reg.send(SESSION, "second")
    # Wait for the second turn to terminate — two result lines arrive either way.
    await _wait_until(lambda: sum(1 for k, _ in kinds() if k == "result") >= 2)

    # No stray abort, exactly one "stopped", and the second prompt paired with its own
    # reply in order — no off-by-one shift.
    assert kinds() == [
        ("user", "first"),
        ("text", "working"),
        ("result", "stopped"),
        ("user", "second"),
        ("text", "answer to second"),
        ("result", "success"),
    ]
    assert reg.active_surfaces() == [SESSION]
    await reg.shutdown_all()


class NeverTerminatesClient(FakeClient):
    """Like SharedStreamClient, but interrupt() streams a trailing chunk and NEVER a
    terminal — modeling an SDK that drops the abort result. The bounded drain must give
    up rather than wedge the session."""

    def __init__(self, options=None):
        super().__init__(options)
        self._stream: asyncio.Queue = asyncio.Queue()
        self.interrupt_called = False

    async def query(self, prompt):
        await super().query(prompt)
        self._stream.put_nowait(
            AssistantMessage(content=[TextBlock(text="working")], model="test")
        )

    async def receive_response(self):
        while True:
            msg = await self._stream.get()
            yield msg
            if isinstance(msg, ResultMessage):
                return

    async def interrupt(self):
        self.interrupt_called = True
        self._stream.put_nowait(
            AssistantMessage(content=[TextBlock(text="trailing")], model="test")
        )
        # No terminal result is ever emitted.


async def test_interrupt_drain_is_time_bounded_when_no_terminal_arrives(monkeypatch):
    # If the SDK never emits a terminal after an interrupt, the drain must time out
    # rather than hang: the turn returns, thinking clears, and the session stays open.
    _seed_session(SESSION, session_type="chat")
    store.get_or_create(SESSION).activity.clear()
    monkeypatch.setattr(agent_session, "_INTERRUPT_DRAIN_SECONDS", 0.05)
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: NeverTerminatesClient(options)
    )
    reg = AgentSessionRegistry()

    def kinds():
        return [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]

    await reg.send(SESSION, "long task")
    await _wait_until(lambda: ("text", "working") in kinds())

    await reg.interrupt(SESSION)
    await _wait_until(lambda: store.get_or_create(SESSION).thinking is False)

    assert ("result", "stopped") in kinds()
    assert not any(text == "error_during_execution" for _, text in kinds())
    assert reg.active_surfaces() == [SESSION]
    await reg.shutdown_all()


async def test_chat_session_uses_the_general_prompt_with_its_surface_id():
    _seed_session("chat-p", session_type="chat")
    reg = AgentSessionRegistry()

    await reg.send("chat-p", "hi")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    prompt = FakeClient.instances[0].options.system_prompt
    assert prompt.startswith(agent_session.CVI_CHAT_SYSTEM_PROMPT)
    assert "chat-p" in prompt  # the agent is told the surface to render to
    await reg.shutdown_all()


def test_with_surface_id_appends_the_id_and_instruction():
    out = agent_session.with_surface_id("BASE PROMPT", "surface-123")
    assert out.startswith("BASE PROMPT")
    assert "surface-123" in out
    assert "every cvi tool" in out
    assert "default" in out  # explicitly warns the agent off guessing "default"


async def test_resumes_the_recorded_session():
    _seed_session(SESSION, agent_session_id="sdk-xyz")
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "pick up where we left off")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    # The client continues the prior conversation rather than starting blank.
    assert FakeClient.instances[0].options.resume == "sdk-xyz"
    await reg.shutdown_all()


async def test_starts_fresh_when_no_session_recorded():
    _seed_session(SESSION)  # agent_session_id is NULL
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hello")
    await _wait_until(lambda: len(FakeClient.instances) == 1)

    assert FakeClient.instances[0].options.resume is None
    await reg.shutdown_all()


async def test_falls_back_to_fresh_when_resume_fails(monkeypatch):
    _seed_session(SESSION, agent_session_id="stale-id")
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


async def test_records_its_sdk_session_id_then_resumes_it_next_time(monkeypatch):
    # A turn reports the SDK session id; it's persisted, and a fresh session for the
    # same surface (after this one closed) reopens with resume set to it.
    _seed_session(SESSION)  # agent_session_id is NULL

    class IdClient(FakeClient):
        async def receive_response(self):
            yield AssistantMessage(content=[TextBlock(text="hi")], model="test")
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="sdk-new",
            )

    monkeypatch.setattr(agent_session, "ClaudeSDKClient", lambda options=None: IdClient(options))
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "hello")
    await _wait_until(lambda: sessions.get_session(SESSION)["agent_session_id"] == "sdk-new")
    await reg.shutdown_all()

    # A new session for the same surface resumes from the recorded id.
    reg2 = AgentSessionRegistry()
    await reg2.send(SESSION, "again")
    await _wait_until(lambda: len(FakeClient.instances) >= 2)
    assert FakeClient.instances[-1].options.resume == "sdk-new"
    await reg2.shutdown_all()


class _FixedTitleGen:
    """Always returns a fixed title; counts calls."""

    def __init__(self, title="Generated Title"):
        self._title = title
        self.calls = 0

    async def generate(self, message):
        self.calls += 1
        return titles.TitleResult(self._title)


class _FlakyTitleGen:
    """Fails (returns None) on the first call, succeeds after."""

    def __init__(self, title="Second Try"):
        self._title = title
        self.calls = 0

    async def generate(self, message):
        self.calls += 1
        return titles.TitleResult(None if self.calls == 1 else self._title)


class _GatedTitleGen:
    """Blocks each call on a per-call gate so two attempts can be held in flight at
    once — to exercise the race-safe 'keep the first successful' guarantee. Keyed by
    call order rather than the message, because concurrent attempts read the same
    rolling-window input and so can't be told apart by content."""

    def __init__(self):
        self.gates: dict[int, asyncio.Event] = {}
        self.done: set[int] = set()
        self.calls = 0

    def gate(self, call: int) -> asyncio.Event:
        return self.gates.setdefault(call, asyncio.Event())

    async def generate(self, message):
        self.calls += 1
        call = self.calls  # assigned before any await, so each call gets a distinct id
        await self.gate(call).wait()
        self.done.add(call)
        return titles.TitleResult(f"title-{call}")


async def test_first_text_message_titles_an_untitled_chat(monkeypatch):
    chat = sessions.create_chat_session()  # type chat, title "New chat"
    monkeypatch.setattr(titles, "generator", _FixedTitleGen("Fix the parser"))
    reg = AgentSessionRegistry()
    ws = FakeWS()
    hub.register(chat, ws)
    try:
        await reg.send(chat, "help me fix the parser")
        await _wait_until(lambda: sessions.get_session(chat)["title"] == "Fix the parser")
    finally:
        hub.unregister(chat, ws)

    # The new title is pushed live to the surface.
    assert {"type": "title", "surface": chat, "payload": {"title": "Fix the parser"}} in ws.received
    await reg.shutdown_all()


async def test_image_only_first_turn_defers_titling_to_the_next_text_message(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _FixedTitleGen("Picture chat")
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()

    # An image-only first turn has no text basis — titling is skipped, not attempted.
    await reg.send(chat, "", images=[agent_session.ImageInput(media_type="image/png", data="QUJD")])
    await _wait_until(lambda: len(FakeClient.instances) == 1)
    assert gen.calls == 0
    assert sessions.get_session(chat)["title"] == "New chat"

    # The next message with text titles it.
    await reg.send(chat, "what is in this picture")
    await _wait_until(lambda: sessions.get_session(chat)["title"] == "Picture chat")
    await reg.shutdown_all()


async def test_failed_titling_retries_on_the_next_message(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _FlakyTitleGen("Second Try")
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()

    await reg.send(chat, "first")
    await _wait_until(lambda: gen.calls == 1)
    assert sessions.get_session(chat)["title"] == "New chat"  # first attempt failed

    await reg.send(chat, "second")
    await _wait_until(lambda: sessions.get_session(chat)["title"] == "Second Try")
    await reg.shutdown_all()


async def test_titling_stops_after_the_first_success(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _FixedTitleGen("Done")
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()

    await reg.send(chat, "one")
    await _wait_until(lambda: sessions.get_session(chat)["title"] == "Done")
    await reg.send(chat, "two")
    await reg.send(chat, "three")
    # Drain the turns so an erroneous extra title attempt would have run by now.
    await _wait_until(lambda: FakeClient.instances[0].queried == ["one", "two", "three"])

    assert gen.calls == 1  # flag flipped after success; no further attempts
    await reg.shutdown_all()


async def test_keeps_the_first_successful_title_under_concurrency(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _GatedTitleGen()
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()
    ws = FakeWS()
    hub.register(chat, ws)
    try:
        # Two messages before any title resolves → two concurrent attempts in flight.
        await reg.send(chat, "a")
        await reg.send(chat, "b")
        await _wait_until(lambda: gen.calls == 2)

        # Let the first attempt win; it titles the chat.
        gen.gate(1).set()
        await _wait_until(lambda: sessions.get_session(chat)["title"] == "title-1")

        # The second finishes after — its conditional write no-ops and must not clobber.
        gen.gate(2).set()
        await _wait_until(lambda: 2 in gen.done)
        assert sessions.get_session(chat)["title"] == "title-1"
        title_frames = [m for m in ws.received if m["type"] == "title"]
        assert title_frames == [{"type": "title", "surface": chat, "payload": {"title": "title-1"}}]
    finally:
        hub.unregister(chat, ws)
    await reg.shutdown_all()


async def test_prompt_gets_a_generated_summary(monkeypatch):
    _seed_session(SESSION, session_type="chat")
    store.get_or_create(SESSION).activity.clear()
    monkeypatch.setattr(titles, "summarizer", _FixedTitleGen("fix the parser"))
    reg = AgentSessionRegistry()
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await reg.send(SESSION, "can you help me fix the parser please")
        await _wait_until(
            lambda: any(m.get("type") == "prompt_summary" for m in ws.received)
        )
    finally:
        hub.unregister(SESSION, ws)

    summary_event = next(m for m in ws.received if m["type"] == "prompt_summary")
    assert summary_event["payload"] == {"index": 0, "text": "fix the parser"}
    # The summary also lands on the stored prompt entry (rides the snapshot)...
    user_entry = next(e for e in store.get_or_create(SESSION).activity if e.kind == "user")
    assert user_entry.summary == "fix the parser"
    # ...and is written back to its persisted row so it survives a restart.
    row = next(r for r in messages.list_messages(SESSION) if r["id"] == user_entry.message_id)
    assert row["summary"] == "fix the parser"
    await reg.shutdown_all()


async def test_chat_with_an_explicit_title_is_not_auto_titled(monkeypatch):
    chat = sessions.create_chat_session("My Title")
    gen = _FixedTitleGen()
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()

    await reg.send(chat, "hello")
    await _wait_until(lambda: len(FakeClient.instances) == 1)
    assert gen.calls == 0
    assert sessions.get_session(chat)["title"] == "My Title"
    await reg.shutdown_all()


class _RecordingTitleGen:
    """Returns a distinct title per call and records the input each call received,
    so a test can assert both the cadence and what the refresh was fed."""

    def __init__(self):
        self.calls = 0
        self.inputs: list[str] = []

    async def generate(self, message):
        self.calls += 1
        self.inputs.append(message)
        return titles.TitleResult(f"Title {self.calls}")


async def test_title_refreshes_every_five_prompts_from_the_recent_window(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _RecordingTitleGen()
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()
    ws = FakeWS()
    hub.register(chat, ws)
    try:
        # Prompt 1 → the initial title.
        await reg.send(chat, "one")
        await _wait_until(lambda: sessions.get_session(chat)["title"] == "Title 1")

        # Prompts 2-4 → no regeneration (cadence not reached).
        for text in ("two", "three", "four"):
            await reg.send(chat, text)
        await _wait_until(
            lambda: FakeClient.instances[0].queried[:4] == ["one", "two", "three", "four"]
        )
        assert gen.calls == 1
        assert sessions.get_session(chat)["title"] == "Title 1"

        # Prompt 5 → refresh overwrites the title and broadcasts live.
        await reg.send(chat, "five")
        await _wait_until(lambda: sessions.get_session(chat)["title"] == "Title 2")
    finally:
        hub.unregister(chat, ws)

    assert {"type": "title", "surface": chat, "payload": {"title": "Title 2"}} in ws.received
    # The refresh is fed the recent-message window, newest-first.
    assert gen.inputs[-1] == "five\nfour\nthree\ntwo\none"
    await reg.shutdown_all()


async def test_image_only_turn_does_not_advance_the_refresh_cadence(monkeypatch):
    chat = sessions.create_chat_session()
    gen = _RecordingTitleGen()
    monkeypatch.setattr(titles, "generator", gen)
    reg = AgentSessionRegistry()

    # Prompt 1 (text) → initial title.
    await reg.send(chat, "one")
    await _wait_until(lambda: sessions.get_session(chat)["title"] == "Title 1")

    # An image-only turn carries no text — it must not count toward the cadence.
    await reg.send(chat, "", images=[agent_session.ImageInput(media_type="image/png", data="QUJD")])
    for text in ("two", "three", "four"):
        await reg.send(chat, text)
    await _wait_until(
        lambda: [q for q in FakeClient.instances[0].queried if isinstance(q, str)]
        == ["one", "two", "three", "four"]
    )
    # Only four *text* prompts so far (the image didn't count) → no refresh yet.
    assert gen.calls == 1
    assert sessions.get_session(chat)["title"] == "Title 1"

    # The fifth text prompt reaches the cadence and refreshes.
    await reg.send(chat, "five")
    await _wait_until(lambda: sessions.get_session(chat)["title"] == "Title 2")
    await reg.shutdown_all()


class _UsageClient(FakeClient):
    """A turn client whose result carries token usage, to exercise token accounting."""

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text="on it")], model="test")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=SESSION,
            usage={
                "output_tokens": 30,
                "input_tokens": 500,
                "cache_read_input_tokens": 1000,
            },
        )


class _UsageTitleGen:
    """A title/summary generator that reports token usage on every call."""

    async def generate(self, message):
        return titles.TitleResult("A Title", output_tokens=7, input_tokens=70)


async def test_turn_records_token_usage_attributed_to_its_prompt(monkeypatch):
    _seed_session(SESSION)
    store.get_or_create(SESSION).activity.clear()
    monkeypatch.setattr(
        agent_session, "ClaudeSDKClient", lambda options=None: _UsageClient(options)
    )
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "do the thing")
    # output 30; input 500 + 1000 cache-read = 1500.
    await _wait_until(lambda: token_usage.session_totals(SESSION) == (30, 1500))

    prompt = next(m for m in messages.list_messages(SESSION) if m["kind"] == "user")
    assert token_usage.tokens_for_message(prompt["id"]) == (30, 1500)
    await reg.shutdown_all()


async def test_title_and_summary_calls_record_token_usage(monkeypatch):
    chat = sessions.create_chat_session()
    monkeypatch.setattr(titles, "generator", _UsageTitleGen())
    monkeypatch.setattr(titles, "summarizer", _UsageTitleGen())
    reg = AgentSessionRegistry()

    await reg.send(chat, "hello there")
    # The default FakeClient turn reports no usage; the title and summary sub-calls
    # each report 7 output / 70 input → 14 / 140 total.
    await _wait_until(lambda: token_usage.session_totals(chat) == (14, 140))
    await reg.shutdown_all()


async def test_answer_records_the_choice_and_runs_a_non_recording_turn(monkeypatch):
    _seed_session(SESSION)
    store.get_or_create(SESSION).activity.clear()
    # A picker awaiting an answer.
    store.append_activity(
        SESSION, "ask", "pick", ask_id="a1", questions=[{"question": "Q", "options": []}]
    )
    reg = AgentSessionRegistry()
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await reg.answer(SESSION, "a1", "Approach: Custom modal")
        await _wait_until(
            lambda: any(e.kind == "result" for e in store.get_or_create(SESSION).activity)
        )
    finally:
        hub.unregister(SESSION, ws)

    activity = store.get_or_create(SESSION).activity
    ask = next(e for e in activity if e.kind == "ask")
    assert ask.answer == "Approach: Custom modal"  # the picker is locked to the choice
    # No duplicate user bubble — the picker is the record of the answer.
    assert not any(e.kind == "user" for e in activity)
    # The agent still received the answer and ran the turn.
    assert FakeClient.instances[0].queried == ["Approach: Custom modal"]
    await reg.shutdown_all()


async def test_send_recreates_a_session_whose_consumer_has_exited(monkeypatch):
    # Simulate the window between a session's idle serve-loop returning and _discard:
    # a dead session is still registered. A new send must recreate it and actually run
    # the turn, not enqueue onto the dead queue and vanish.
    _seed_session(SESSION)
    store.get_or_create(SESSION).activity.clear()
    reg = AgentSessionRegistry()

    await reg.send(SESSION, "first")
    await _wait_until(lambda: reg.active_surfaces() == [SESSION])
    dead = reg._sessions[SESSION]

    # Force the consumer task to finish, then re-register the now-dead session to model
    # the pre-_discard window.
    dead._task.cancel()
    try:
        await dead._task
    except asyncio.CancelledError:
        pass
    reg._sessions[SESSION] = dead
    assert dead.is_live() is False

    FakeClient.instances.clear()
    store.get_or_create(SESSION).activity.clear()

    await reg.send(SESSION, "second")
    await _wait_until(
        lambda: ("text", "on it")
        in [(e.kind, e.text) for e in store.get_or_create(SESSION).activity]
    )
    # A fresh session ran the turn (not the dead one).
    assert reg._sessions[SESSION] is not dead
    assert FakeClient.instances[-1].queried == ["second"]
    await reg.shutdown_all()
