"""Long-lived, interactive Claude sessions — one per surface.

A review (``review_runner``) is fire-and-forget: open a client, send one prompt,
drain, close. A *conversation* is the opposite — the client stays open and the user
sends turns over time. The Agent SDK supports this, but with a hard constraint: the
open client keeps a persistent reader task group alive from connect to disconnect
and cannot be used across async contexts. So each session has a single **owner task**
that holds the client open and drains an input queue; the WebSocket handler only
enqueues text. That also serializes turns for free — a message that arrives mid-turn
waits behind the current one.

Sessions start lazily on the first message, are keyed by surface, survive browser
reconnects, and are reaped on idle or daemon shutdown. A review surface runs against
its worktree (as cwd) with the review prompt; a general chat surface has no worktree
(cwd is None) and gets the general chat prompt. The only thing that can't chat is a
surface with no session row at all. Read-only (the options' permission gate denies
edits).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage

from daemon import sessions, titles
from daemon.activity_relay import relay_message_activity
from daemon.mcp_server import (
    CVI_CHAT_SYSTEM_PROMPT,
    CVI_REVIEW_SYSTEM_PROMPT,
    broadcast_prompt_summary,
    broadcast_thinking,
    broadcast_title,
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


@dataclass
class ImageInput:
    # A pasted image: its MIME type and raw base64 (no data-URL prefix).
    media_type: str
    data: str


@dataclass
class ChatTurn:
    # One user turn: text plus an optional pasted image.
    text: str
    image: ImageInput | None = None


async def _user_message_stream(turn: ChatTurn) -> AsyncIterator[dict[str, Any]]:
    """Yield the single multimodal user message for ClaudeSDKClient.query's streaming
    form (text-only turns take the plain-string fast path instead). The dict mirrors
    what the SDK builds for a string prompt — carries parent_tool_use_id; the SDK
    fills in session_id."""
    blocks: list[dict[str, Any]] = []
    if turn.text:
        blocks.append({"type": "text", "text": turn.text})
    if turn.image is not None:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": turn.image.media_type,
                    "data": turn.image.data,
                },
            }
        )
    yield {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
    }


def with_surface_id(prompt: str, surface: str) -> str:
    """Append the agent's surface id to its system prompt so cvi tool calls target
    the right surface. Mirrors what the review runner bakes into _review_prompt:
    without it the chat agent guesses the surface (e.g. 'default') and renders into
    a surface no browser is watching."""
    return (
        f"{prompt}\n\nYour surface id is `{surface}`. Pass it as the `surface` "
        "argument to every cvi tool (render_html, render_file). This id is fixed for "
        'the whole session — do not guess it, do not use "default", and do not query '
        "the daemon for it."
    )


class AgentSession:
    """One open Claude client bound to a surface, fed user turns via a queue."""

    def __init__(
        self,
        registry: AgentSessionRegistry,
        surface: str,
        worktree: str | None,
        system_prompt: str,
        resume: str | None = None,
        needs_title: bool = False,
    ) -> None:
        self._registry = registry
        self._surface = surface
        self._worktree = worktree
        self._system_prompt = system_prompt
        self._resume = resume
        # True while this chat is still on the default title; flipped off once any
        # titling attempt resolves, so we stop spawning title calls per message.
        self._needs_title = needs_title
        self._title_tasks: set[asyncio.Task[None]] = set()
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

    def _options(self, resume: str | None) -> object:
        return build_agent_options(
            cwd=self._worktree,
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
            self._registry._discard(self._surface)

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
        marker = f"[image] {turn.text}".rstrip() if turn.image is not None else turn.text
        entry = await record_activity(self._surface, "user", marker)
        # Generate this prompt's one-line outline-rail summary in the background.
        index = self._prompt_count
        self._prompt_count += 1
        self._summarize_prompt(index, entry, turn.text)
        await broadcast_thinking(self._surface, True)
        self._turn_active = True
        self._interrupting = False
        try:
            for attempt in range(1, _MAX_TURN_ATTEMPTS + 1):
                relayed_content, retry_status = await self._attempt_turn(client, turn)
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
        self, client: ClaudeSDKClient, turn: ChatTurn
    ) -> tuple[bool, int | None]:
        """Run one query attempt, relaying messages as they stream. Returns
        ``(relayed_content, retry_status)``: ``retry_status`` is the HTTP status of
        a transient API error worth retrying (the errored result is *suppressed*
        from the feed so a retry stays silent), or ``None`` when the turn finished —
        success, or an error already surfaced via the relay. ``relayed_content`` is
        True once any assistant message has streamed, marking the point past which a
        retry would duplicate output."""
        if turn.image is None:
            await client.query(turn.text)  # text-only: the plain-string fast path
        else:
            await client.query(_user_message_stream(turn))
        relayed_content = False
        async for message in client.receive_response():
            # An interrupt aborts the turn; stop relaying so the SDK's terminal
            # abort result doesn't show up in the feed (the clean "stopped" line
            # is recorded by interrupt() instead).
            if self._interrupting:
                return relayed_content, None
            if (
                isinstance(message, ResultMessage)
                and message.is_error
                and message.api_error_status in _RETRYABLE_API_STATUSES
            ):
                return relayed_content, message.api_error_status
            await relay_message_activity(self._surface, message)
            if isinstance(message, AssistantMessage):
                relayed_content = True
        return relayed_content, None

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
        """If this chat still needs a title and the message has text to title from,
        kick off a background titling attempt. Fire-and-forget — never blocks the
        turn. Image-only turns (no text) are skipped, so titling falls to a later
        message; failed attempts leave the flag set and retry on the next message."""
        if not (self._needs_title and text):
            return
        task = asyncio.create_task(self._run_titling(text))
        self._title_tasks.add(task)
        task.add_done_callback(self._title_tasks.discard)

    async def _run_titling(self, text: str) -> None:
        try:
            title = await titles.generator.generate(text)
            if not title:
                return  # leave _needs_title set — retried on the next message
            # The title is resolved now (this attempt or a concurrent one), so stop
            # spawning more. The conditional write keeps the first successful attempt:
            # only the one that actually changed the row broadcasts the live update.
            self._needs_title = False
            changed = await asyncio.to_thread(sessions.set_generated_title, self._surface, title)
            if changed:
                await broadcast_title(self._surface, title)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("titling failed (surface=%s)", self._surface, exc_info=True)

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
            summary = await titles.summarizer.generate(text)
            if not summary:
                return
            entry.summary = summary  # rides the connect snapshot for late joiners
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

    async def send(self, surface: str, text: str, image: ImageInput | None = None) -> None:
        """Route a user message (text plus an optional pasted image) to the surface's
        session, starting one if needed. A surface with no session row can't chat —
        recorded observably, not silently. A chat session has no worktree (cwd None);
        a review session runs against its worktree and continues its conversation via
        the recorded SDK session id."""
        if surface not in self._sessions:
            session = await asyncio.to_thread(sessions.get_session, surface)
            if session is None:
                log.warning("no session for surface %s; cannot start chat", surface)
                await record_activity(surface, "result", "no session for this surface")
                return
            worktree = session.get("worktree_path")  # None for a worktree-free chat
            system_prompt = (
                CVI_REVIEW_SYSTEM_PROMPT
                if session.get("type") == "review"
                else CVI_CHAT_SYSTEM_PROMPT
            )
            # Resume the review's SDK session when one was recorded, so chat
            # continues that conversation instead of starting blank.
            resume = session.get("agent_session_id")
            # An untitled chat gets auto-titled from its messages. Re-derived from the
            # DB each time the session is (re)created, so it self-heals across idle
            # reaping / daemon restart.
            needs_title = session.get("type") == "chat" and session.get("title") in (
                None,
                sessions.DEFAULT_CHAT_TITLE,
            )
            self._sessions[surface] = AgentSession(
                self,
                surface,
                worktree,
                system_prompt=system_prompt,
                resume=resume,
                needs_title=needs_title,
            )
        self._sessions[surface].maybe_title(text)
        # The turn's user line is recorded when the turn runs (see _run_turn), not
        # here, so a message queued behind an in-flight turn can't appear above that
        # turn's answer.
        self._sessions[surface].enqueue(ChatTurn(text=text, image=image))

    async def interrupt(self, surface: str) -> None:
        """Stop an in-flight turn on the surface, leaving the session open for the
        next message. A no-op when the surface has no live session."""
        session = self._sessions.get(surface)
        if session is not None:
            await session.interrupt()

    def _discard(self, surface: str) -> None:
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
