"""Long-lived, interactive Claude sessions — one per surface.

A *conversation* keeps its Claude client open while the user sends turns over time.
The Agent SDK supports this with a hard constraint: the open client keeps a persistent
reader task group alive from connect to disconnect and cannot be used across async
contexts. So each session has a single **owner task** that holds the client open and
drains an input queue; the WebSocket handler only enqueues text. That also serializes
turns for free — a message that arrives mid-turn waits behind the current one.

Sessions start lazily on the first message, are keyed by surface, survive browser
reconnects, and are reaped on idle or daemon shutdown. The only thing that can't chat
is a surface with no session row at all.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage

from daemon import messages, sessions, titles, token_usage
from daemon.activity_relay import relay_message_activity
from daemon.mcp_server import (
    CVI_CHAT_SYSTEM_PROMPT,
    broadcast_answer,
    broadcast_prompt_summary,
    broadcast_thinking,
    broadcast_title,
    broadcast_tokens,
    build_agent_options,
    record_activity,
)
from daemon.view_state import ActivityEntry

log = logging.getLogger(__name__)

# Close an open session after this long with no new message and no active turn.
AGENT_IDLE_SECONDS = 1800

# A transient API failure surfaces as a terminal ResultMessage with is_error=True
# and one of these HTTP statuses in api_error_status (overload/server/rate-limit).
# The interactive CLI retries these transparently; CVI must too, or a momentary
# 529 ("Overloaded") becomes a visible, terminal turn error.
_RETRYABLE_API_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
# Total attempts per turn (1 initial + retries), and exponential backoff with
# full jitter between them (seconds), capped so a hung overload can't stall a turn.
_MAX_TURN_ATTEMPTS = 4
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

# After an interrupt, the SDK leaves the turn's terminal abort result pending in its
# single shared stream; the turn loop drains it (see _attempt_turn / _drain_interrupted)
# so it can't leak into the next turn and shift the feed. Bound the drain so a terminal
# that never arrives can't wedge the session — a possibly-dirty next turn beats a
# permanently stuck one.
_INTERRUPT_DRAIN_SECONDS = 5.0


@dataclass
class ImageInput:
    # A pasted image: its MIME type and raw base64 (no data-URL prefix).
    media_type: str
    data: str


@dataclass
class ChatTurn:
    # One user turn: text plus zero or more pasted/dropped images. `record_user` is
    # False for a picker answer, whose choice is already shown on the picker entry — so
    # the turn feeds the agent without recording a duplicate user bubble.
    text: str
    images: list[ImageInput] = field(default_factory=list)
    record_user: bool = True


async def _user_message_stream(turn: ChatTurn) -> AsyncIterator[dict[str, Any]]:
    """Yield the single multimodal user message for ClaudeSDKClient.query's streaming
    form (text-only turns take the plain-string fast path instead). The dict mirrors
    what the SDK builds for a string prompt — carries parent_tool_use_id; the SDK
    fills in session_id. One image block per attached image, in order, after the text."""
    blocks: list[dict[str, Any]] = []
    if turn.text:
        blocks.append({"type": "text", "text": turn.text})
    for image in turn.images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": image.data,
                },
            }
        )
    yield {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
    }


def _turn_marker(turn: ChatTurn) -> str:
    """The activity-feed label for a user turn: marks attached images by count (never
    dumps base64). No images → just the text; one → `[image] <text>`; many →
    `[N images] <text>`."""
    n = len(turn.images)
    if n == 0:
        return turn.text
    prefix = "[image]" if n == 1 else f"[{n} images]"
    return f"{prefix} {turn.text}".rstrip()


def with_surface_id(prompt: str, surface: str) -> str:
    """Append the agent's surface id to its system prompt so cvi tool calls target
    the right surface. Without it the chat agent guesses the surface (e.g. 'default')
    and renders into a surface no browser is watching."""
    return (
        f"{prompt}\n\nYour surface id is `{surface}`. Pass it as the `surface` "
        "argument to every cvi tool. This id is fixed for "
        'the whole session — do not guess it, do not use "default", and do not query '
        "the daemon for it."
    )


class AgentSession:
    """One open Claude client bound to a surface, fed user turns via a queue."""

    def __init__(
        self,
        registry: AgentSessionRegistry,
        surface: str,
        system_prompt: str,
        resume: str | None = None,
        needs_title: bool = False,
    ) -> None:
        self._registry = registry
        self._surface = surface
        self._system_prompt = system_prompt
        self._resume = resume
        # The SDK session id this chat is running under, persisted so a later session
        # (after idle-close / daemon restart) resumes the conversation. Seeded with the
        # id we opened on; updated when a turn's result reports a different one.
        self._sdk_session_id = resume
        # True while this chat is still on the default title; flipped off once any
        # titling attempt resolves, so we stop spawning title calls per message.
        self._needs_title = needs_title
        self._title_tasks: set[asyncio.Task[None]] = set()
        # Periodic title refresh: a rolling window of the most recent user messages
        # feeds a regeneration every TITLE_REFRESH_EVERY text prompts. The counter is
        # at send time (where titling lives), distinct from the execution-time
        # _prompt_count used for rail summaries. _title_refreshing single-flights the
        # refresh so a burst of prompts can't stack overlapping calls.
        self._recent_user_msgs: deque[str] = deque(maxlen=titles.TITLE_WINDOW_MESSAGES)
        self._title_prompt_count = 0
        self._title_refreshing = False
        # Per-prompt outline-rail summaries: a monotonic prompt counter (the rail's
        # `prompt-N` index) and the in-flight summary tasks.
        self._prompt_count = 0
        self._summary_tasks: set[asyncio.Task[None]] = set()
        self._queue: asyncio.Queue[ChatTurn] = asyncio.Queue()
        # The live client while a connection is open, so a concurrent caller can
        # interrupt the in-flight turn. `_turn_active` gates interrupt to a running
        # turn; `_interrupting` tells the relay loop to stop relaying once the SDK
        # aborts (so the interrupt's terminal result doesn't litter the feed).
        self._client: ClaudeSDKClient | None = None
        self._turn_active = False
        self._interrupting = False
        self._task = asyncio.create_task(self._run())

    def enqueue(self, turn: ChatTurn) -> None:
        self._queue.put_nowait(turn)

    def is_live(self) -> bool:
        """True while the owner task is still consuming the queue. False once it has
        exited (idle timeout / error), so the registry won't enqueue onto a dead queue."""
        return not self._task.done()

    def _options(self, resume: str | None) -> object:
        return build_agent_options(
            system_prompt=with_surface_id(self._system_prompt, self._surface),
            resume=resume,
        )

    async def _run(self) -> None:
        try:
            try:
                await self._serve(self._resume)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failure on the resume path is most likely a stale/missing prior
                # session — fall back to a fresh one (once) so chat still works,
                # observably (P4). With no resume id, it's a genuine session error.
                if self._resume is None:
                    raise
                log.warning(
                    "could not resume session for surface %s; starting fresh",
                    self._surface,
                    exc_info=True,
                )
                await record_activity(
                    self._surface, "result", "could not resume prior session; starting fresh"
                )
                await self._serve(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("agent session failed (surface=%s)", self._surface, exc_info=True)
            await record_activity(self._surface, "result", "session error")
        finally:
            self._registry._discard(self._surface, self)

    async def _serve(self, resume: str | None) -> None:
        async with ClaudeSDKClient(options=self._options(resume)) as client:
            self._client = client
            try:
                while True:
                    try:
                        turn = await asyncio.wait_for(self._queue.get(), AGENT_IDLE_SECONDS)
                    except TimeoutError:
                        log.info("agent session idle, closing (surface=%s)", self._surface)
                        return
                    await self._run_turn(client, turn)
            finally:
                self._client = None

    async def _run_turn(self, client: ClaudeSDKClient, turn: ChatTurn) -> None:
        """Run one user turn, retrying transient API failures with exponential
        backoff + jitter so a momentary overload (529) doesn't surface as a turn
        error — matching how the interactive CLI swallows and retries them.

        A genuinely failed turn is still surfaced (P4) but keeps the session alive
        for the next message. The thinking flag brackets the whole turn (cleared in
        the finally) so the indicator never sticks on after success, error, or cancel."""
        # Record the user's turn at execution time, not enqueue time, so the
        # transcript always pairs this prompt with the reply that follows it. A
        # message sent while a prior turn is still streaming stays queued (invisible)
        # until its turn runs, instead of landing above the prior turn's answer.
        # A picker answer (record_user=False) is already shown on its picker entry, so
        # skip recording a duplicate user bubble (and its rail summary); the turn still
        # runs so the agent gets the answer.
        prompt_message_id: int | None = None
        if turn.record_user:
            marker = _turn_marker(turn)
            entry = await record_activity(self._surface, "user", marker)
            # Generate this prompt's one-line outline-rail summary in the background.
            index = self._prompt_count
            self._prompt_count += 1
            self._summarize_prompt(index, entry, turn.text)
            prompt_message_id = entry.message_id
        await broadcast_thinking(self._surface, True)
        self._turn_active = True
        self._interrupting = False
        try:
            for attempt in range(1, _MAX_TURN_ATTEMPTS + 1):
                relayed_content, retry_status = await self._attempt_turn(
                    client, turn, prompt_message_id
                )
                if retry_status is None:
                    return  # completed: success, or an error already relayed
                # Once content has streamed we can't cleanly re-run (it would
                # duplicate); and the final attempt has no retry left. Either way,
                # surface the failure rather than retry.
                if relayed_content or attempt == _MAX_TURN_ATTEMPTS:
                    await record_activity(
                        self._surface, "result", f"API error {retry_status}"
                    )
                    return
                delay = min(_RETRY_MAX_DELAY, _RETRY_BASE_DELAY * 2 ** (attempt - 1))
                delay += random.uniform(0, delay)  # full jitter
                log.warning(
                    "transient API error %s (surface=%s); retrying in %.1fs "
                    "(attempt %d/%d)",
                    retry_status,
                    self._surface,
                    delay,
                    attempt,
                    _MAX_TURN_ATTEMPTS,
                )
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("agent turn failed (surface=%s)", self._surface, exc_info=True)
            await record_activity(self._surface, "result", "turn error")
        finally:
            self._turn_active = False
            await broadcast_thinking(self._surface, False)

    async def _attempt_turn(
        self, client: ClaudeSDKClient, turn: ChatTurn, prompt_message_id: int | None
    ) -> tuple[bool, int | None]:
        """Run one query attempt, relaying messages as they stream. Returns
        ``(relayed_content, retry_status)``: ``retry_status`` is the HTTP status of
        a transient API error worth retrying (the errored result is *suppressed*
        from the feed so a retry stays silent), or ``None`` when the turn finished —
        success, or an error already surfaced via the relay. ``relayed_content`` is
        True once any assistant message has streamed, marking the point past which a
        retry would duplicate output."""
        if not turn.images:
            await client.query(turn.text)  # text-only: the plain-string fast path
        else:
            await client.query(_user_message_stream(turn))
        relayed_content = False
        response = client.receive_response()
        async for message in response:
            # An interrupt aborts the turn. Don't relay (the clean "stopped" line is
            # recorded by interrupt()), but don't abandon the stream either: the SDK
            # leaves this turn's terminal abort result pending in its single shared
            # stream. Drain it here, within the interrupted turn. Abandoning instead
            # would leave that result buffered for the *next* turn's receive_response()
            # to pick up — relayed against the wrong prompt and shifting every later
            # reply down one. The turn loop stays the sole stream consumer (interrupt()
            # never reads it), so there's no two-readers race.
            if self._interrupting:
                await self._drain_interrupted(response)
                return relayed_content, None
            if (
                isinstance(message, ResultMessage)
                and message.is_error
                and message.api_error_status in _RETRYABLE_API_STATUSES
            ):
                return relayed_content, message.api_error_status
            if isinstance(message, ResultMessage):
                await self._remember_sdk_session(message.session_id)
                out, inp = token_usage.usage_tokens(message.usage)
                await self._record_usage("turn", out, inp, prompt_message_id)
            await relay_message_activity(self._surface, message)
            if isinstance(message, AssistantMessage):
                relayed_content = True
        return relayed_content, None

    async def _drain_interrupted(self, response: AsyncIterator[Any]) -> None:
        """Consume and discard the rest of an interrupted turn's messages until
        receive_response() ends on the SDK's terminal abort result, so that result
        can't leak into the next turn's shared stream. Bounded by
        _INTERRUPT_DRAIN_SECONDS (mirroring the idle-read wait_for) so a terminal that
        never arrives can't wedge the session — the next turn opening on a possibly
        dirty stream is strictly better than a permanently stuck one (logged, P4)."""

        async def _drain() -> None:
            async for _ in response:
                pass

        try:
            await asyncio.wait_for(_drain(), _INTERRUPT_DRAIN_SECONDS)
        except TimeoutError:
            log.warning(
                "interrupt drain timed out (surface=%s); SDK emitted no terminal "
                "result after interrupt",
                self._surface,
            )

    async def _record_usage(
        self, kind: str, output_tokens: int, input_tokens: int, message_id: int | None = None
    ) -> None:
        """Record one LLM call's token usage toward the session total, and log it.
        No-op when the call reported nothing (e.g. a failed sub-call)."""
        if not (output_tokens or input_tokens):
            return
        await asyncio.to_thread(
            token_usage.append_usage,
            self._surface,
            kind,
            output_tokens,
            input_tokens,
            message_id,
        )
        log.info(
            "token usage",
            extra={
                "surface": self._surface,
                "kind": kind,
                "output_tokens": output_tokens,
                "input_tokens": input_tokens,
            },
        )
        await broadcast_tokens(self._surface, output_tokens, input_tokens)

    async def _remember_sdk_session(self, session_id: str | None) -> None:
        """Persist the SDK session id so a later session for this surface resumes the
        conversation. A no-op unless it changed, so a steady conversation doesn't write
        to the DB every turn."""
        if not session_id or session_id == self._sdk_session_id:
            return
        self._sdk_session_id = session_id
        await asyncio.to_thread(sessions.set_agent_session_id, self._surface, session_id)

    async def interrupt(self) -> None:
        """Stop the in-flight turn without closing the session, so the next message
        still works. The SDK interrupt ends the active receive loop; _run_turn's
        finally clears the thinking flag. A no-op when no turn is running."""
        client = self._client
        if client is None or not self._turn_active:
            return
        self._interrupting = True
        try:
            await client.interrupt()
            await record_activity(self._surface, "result", "stopped")
        except Exception:
            log.warning("interrupt failed (surface=%s)", self._surface, exc_info=True)

    def maybe_title(self, text: str) -> None:
        """Drive titling off each text-bearing user message. Image-only turns (no text)
        are skipped, so they don't advance the window or the refresh cadence. While the
        chat is still untitled, kick off an initial titling attempt (retried on the next
        message until one lands); once titled, regenerate every TITLE_REFRESH_EVERY
        prompts off the recent-message window. Both are fire-and-forget — never block
        the turn."""
        if not text:
            return
        self._recent_user_msgs.append(text)
        self._title_prompt_count += 1
        # Snapshot the window now, at the prompt, so the attempt titles from the window
        # as of this message — not whatever it's grown to when the task happens to run.
        title_input = self._title_input()
        if self._needs_title:
            self._spawn_title_task(self._run_titling(title_input))
        elif (
            self._title_prompt_count % titles.TITLE_REFRESH_EVERY == 0
            and not self._title_refreshing
        ):
            self._title_refreshing = True
            self._spawn_title_task(self._run_title_refresh(title_input))

    def _spawn_title_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._title_tasks.add(task)
        task.add_done_callback(self._title_tasks.discard)

    def _title_input(self) -> str:
        """The recent-message window fed to the title call, newest-first so generate()'s
        length cap preserves the most recent context."""
        return "\n".join(reversed(self._recent_user_msgs))

    async def _run_titling(self, title_input: str) -> None:
        try:
            result = await titles.generator.generate(title_input)
            await self._record_usage("title", result.output_tokens, result.input_tokens)
            if not result.title:
                return  # leave _needs_title set — retried on the next message
            # The title is resolved now (this attempt or a concurrent one), so stop
            # spawning more. The conditional write keeps the first successful attempt:
            # only the one that actually changed the row broadcasts the live update.
            self._needs_title = False
            changed = await asyncio.to_thread(
                sessions.set_generated_title, self._surface, result.title
            )
            if changed:
                await broadcast_title(self._surface, result.title)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("titling failed (surface=%s)", self._surface, exc_info=True)

    async def _run_title_refresh(self, title_input: str) -> None:
        """Regenerate the title from the recent-message window and overwrite the prior
        one. Single-flighted via _title_refreshing (cleared in finally). Always broadcasts
        the result — we don't track the current title in memory, and re-broadcasting an
        unchanged title is harmless."""
        try:
            result = await titles.generator.generate(title_input)
            await self._record_usage("title", result.output_tokens, result.input_tokens)
            if not result.title:
                return
            await asyncio.to_thread(sessions.overwrite_title, self._surface, result.title)
            await broadcast_title(self._surface, result.title)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("title refresh failed (surface=%s)", self._surface, exc_info=True)
        finally:
            self._title_refreshing = False

    def _summarize_prompt(self, index: int, entry: ActivityEntry, text: str) -> None:
        """Kick off a background one-line summary for the index-th user prompt, used
        as its outline-rail label. Fire-and-forget; image-only turns (no text) are
        skipped (the rail falls back to the prompt text)."""
        if not text:
            return
        task = asyncio.create_task(self._run_summary(index, entry, text))
        self._summary_tasks.add(task)
        task.add_done_callback(self._summary_tasks.discard)

    async def _run_summary(self, index: int, entry: ActivityEntry, text: str) -> None:
        try:
            result = await titles.summarizer.generate(text)
            await self._record_usage(
                "summary", result.output_tokens, result.input_tokens, entry.message_id
            )
            summary = result.title
            if not summary:
                return
            entry.summary = summary  # rides the connect snapshot for late joiners
            if entry.message_id is not None:
                # Persist the summary onto its already-written row so the rail label
                # survives a restart, not just this live broadcast.
                await asyncio.to_thread(
                    messages.set_message_summary, entry.message_id, summary
                )
            await broadcast_prompt_summary(self._surface, index, summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("prompt summary failed (surface=%s)", self._surface, exc_info=True)

    async def aclose(self) -> None:
        for task in (*self._title_tasks, *self._summary_tasks):
            task.cancel()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


class AgentSessionRegistry:
    """The live conversational sessions, keyed by surface. In-memory, single-process
    (mirrors ``store`` / ``hub``)."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    async def send(
        self,
        surface: str,
        text: str,
        images: list[ImageInput] | None = None,
        record_user: bool = True,
    ) -> None:
        """Route a user message (text plus zero or more pasted/dropped images) to the
        surface's session, starting one if needed. A surface with no session row can't chat —
        recorded observably, not silently. A session resumes its recorded SDK session
        id when one exists, so it continues across reconnect / restart instead of
        starting blank. `record_user=False` feeds the turn without a user bubble (a
        picker answer, already shown on its picker entry)."""
        # Recreate when there's no session OR the existing one's consumer task has
        # already exited (idle timeout). Otherwise a message arriving in the window
        # between the serve loop returning and _discard running would enqueue onto a
        # dead queue and be silently lost.
        existing = self._sessions.get(surface)
        if existing is None or not existing.is_live():
            session = await asyncio.to_thread(sessions.get_session, surface)
            if session is None:
                log.warning("no session for surface %s; cannot start chat", surface)
                await record_activity(surface, "result", "no session for this surface")
                return
            # Resume the SDK session when one was recorded, so the conversation
            # continues instead of starting blank.
            resume = session.get("agent_session_id")
            # An untitled chat gets auto-titled from its messages. Re-derived from the
            # DB each time the session is (re)created, so it self-heals across idle
            # reaping / daemon restart.
            needs_title = session.get("title") in (None, sessions.DEFAULT_CHAT_TITLE)
            self._sessions[surface] = AgentSession(
                self,
                surface,
                system_prompt=CVI_CHAT_SYSTEM_PROMPT,
                resume=resume,
                needs_title=needs_title,
            )
        self._sessions[surface].maybe_title(text)
        # The turn's user line is recorded when the turn runs (see _run_turn), not
        # here, so a message queued behind an in-flight turn can't appear above that
        # turn's answer.
        self._sessions[surface].enqueue(
            ChatTurn(text=text, images=images or [], record_user=record_user)
        )

    async def answer(self, surface: str, ask_id: str, answer: str) -> None:
        """Apply a picker selection: record the choice on the picker entry (pushed live
        so a reconnecting browser sees the answered state) and feed it to the agent as a
        non-recording turn — no duplicate user bubble, since the picker shows the choice."""
        await broadcast_answer(surface, ask_id, answer)
        await self.send(surface, answer, record_user=False)

    async def interrupt(self, surface: str) -> None:
        """Stop an in-flight turn on the surface, leaving the session open for the
        next message. A no-op when the surface has no live session."""
        session = self._sessions.get(surface)
        if session is not None:
            await session.interrupt()

    def _discard(self, surface: str, session: AgentSession | None = None) -> None:
        # Only remove if the registered session is the one asking to be discarded, so a
        # replacement created after an idle reap (see send) isn't accidentally dropped.
        if session is None or self._sessions.get(surface) is session:
            self._sessions.pop(surface, None)

    def active_surfaces(self) -> list[str]:
        return list(self._sessions)

    async def shutdown_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.aclose()
        # A not-yet-started owner task is cancelled before its finally runs, so it
        # never self-discards — clear unconditionally so the registry ends empty.
        self._sessions.clear()


# The daemon owns a single registry for the whole process.
agents = AgentSessionRegistry()
