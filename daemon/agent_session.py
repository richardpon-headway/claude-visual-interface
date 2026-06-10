"""Long-lived, interactive Claude sessions — one per surface.

A review (``review_runner``) is fire-and-forget: open a client, send one prompt,
drain, close. A *conversation* is the opposite — the client stays open and the user
sends turns over time. The Agent SDK supports this, but with a hard constraint: the
open client keeps a persistent reader task group alive from connect to disconnect
and cannot be used across async contexts. So each session has a single **owner task**
that holds the client open and drains an input queue; the WebSocket handler only
enqueues text. That also serializes turns for free — a message that arrives mid-turn
waits behind the current one.

Sessions start lazily on the first message, are keyed by surface (reusing the
session row's worktree as cwd), survive browser reconnects, and are reaped on idle
or daemon shutdown. Read-only this slice (the options' permission gate denies edits).
"""

from __future__ import annotations

import asyncio
import logging

from claude_agent_sdk import ClaudeSDKClient

from daemon import sessions
from daemon.activity_relay import relay_message_activity
from daemon.mcp_server import CVI_SURFACE_SYSTEM_PROMPT, build_agent_options, record_activity

log = logging.getLogger(__name__)

# Close an open session after this long with no new message and no active turn.
AGENT_IDLE_SECONDS = 1800


class AgentSession:
    """One open Claude client bound to a surface, fed user turns via a queue."""

    def __init__(
        self,
        registry: AgentSessionRegistry,
        surface: str,
        worktree: str,
        resume: str | None = None,
    ) -> None:
        self._registry = registry
        self._surface = surface
        self._worktree = worktree
        self._resume = resume
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task = asyncio.create_task(self._run())

    def enqueue(self, text: str) -> None:
        self._queue.put_nowait(text)

    def _options(self, resume: str | None) -> object:
        return build_agent_options(
            cwd=self._worktree, system_prompt=CVI_SURFACE_SYSTEM_PROMPT, resume=resume
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
                    text = await asyncio.wait_for(self._queue.get(), AGENT_IDLE_SECONDS)
                except TimeoutError:
                    log.info("agent session idle, closing (surface=%s)", self._surface)
                    return
                await self._run_turn(client, text)

    async def _run_turn(self, client: ClaudeSDKClient, text: str) -> None:
        """Run one user turn. A failed turn is surfaced (P4) but keeps the session
        alive for the next message."""
        try:
            await client.query(text)
            async for message in client.receive_response():
                await relay_message_activity(self._surface, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("agent turn failed (surface=%s)", self._surface, exc_info=True)
            await record_activity(self._surface, "result", "turn error")

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

    async def send(self, surface: str, text: str) -> None:
        """Route a user message to the surface's session, starting one if needed.
        A surface with no worktree can't chat — recorded observably, not silently."""
        if surface not in self._sessions:
            session = await asyncio.to_thread(sessions.get_session, surface)
            worktree = session.get("worktree_path") if session else None
            if not worktree:
                log.warning("no worktree for surface %s; cannot start chat", surface)
                await record_activity(surface, "result", "no worktree for this surface")
                return
            # Resume the review's SDK session when one was recorded, so chat
            # continues that conversation instead of starting blank.
            resume = session.get("agent_session_id")
            self._sessions[surface] = AgentSession(self, surface, worktree, resume=resume)
        await record_activity(surface, "user", text)
        self._sessions[surface].enqueue(text)

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
