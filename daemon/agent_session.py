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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ClaudeSDKClient

from daemon import sessions
from daemon.activity_relay import relay_message_activity
from daemon.mcp_server import (
    CVI_CHAT_SYSTEM_PROMPT,
    CVI_REVIEW_SYSTEM_PROMPT,
    broadcast_thinking,
    build_agent_options,
    record_activity,
)

log = logging.getLogger(__name__)

# Close an open session after this long with no new message and no active turn.
AGENT_IDLE_SECONDS = 1800


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
        "argument to every cvi tool (render_html, open_code, highlight_range, etc.). "
        'This id is fixed for the whole session — do not guess it, do not use "default", '
        "and do not query the daemon for it."
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
    ) -> None:
        self._registry = registry
        self._surface = surface
        self._worktree = worktree
        self._system_prompt = system_prompt
        self._resume = resume
        self._queue: asyncio.Queue[ChatTurn] = asyncio.Queue()
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
            while True:
                try:
                    turn = await asyncio.wait_for(self._queue.get(), AGENT_IDLE_SECONDS)
                except TimeoutError:
                    log.info("agent session idle, closing (surface=%s)", self._surface)
                    return
                await self._run_turn(client, turn)

    async def _run_turn(self, client: ClaudeSDKClient, turn: ChatTurn) -> None:
        """Run one user turn. A failed turn is surfaced (P4) but keeps the session
        alive for the next message. The thinking flag brackets the turn (cleared in
        the finally) so the indicator never sticks on after success, error, or cancel."""
        await broadcast_thinking(self._surface, True)
        try:
            if turn.image is None:
                await client.query(turn.text)  # text-only: the plain-string fast path
            else:
                await client.query(_user_message_stream(turn))
            async for message in client.receive_response():
                await relay_message_activity(self._surface, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("agent turn failed (surface=%s)", self._surface, exc_info=True)
            await record_activity(self._surface, "result", "turn error")
        finally:
            await broadcast_thinking(self._surface, False)

    async def aclose(self) -> None:
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
            self._sessions[surface] = AgentSession(
                self, surface, worktree, system_prompt=system_prompt, resume=resume
            )
        # Mark an attached image in the feed without dumping base64.
        marker = f"[image] {text}".rstrip() if image is not None else text
        await record_activity(surface, "user", marker)
        self._sessions[surface].enqueue(ChatTurn(text=text, image=image))

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
