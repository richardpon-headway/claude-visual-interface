"""The review-run seam.

``POST /reviews`` creates a session row and hands off to a ReviewRunner. The real
runner spawns a Claude Agent SDK session over the review worktree — inheriting the
user's Claude Code auth (no alternate key, per the plan) — that reviews the diff
against base_ref and emits findings through the cvi MCP tools, which already
persist and broadcast to the browser. Swap ``runner`` for a fake in tests.

This is the minimal runner: a direct, read-only review prompt. Invoking the
configured review skill (pr-review) via a YAML config is a later slice.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from daemon import findings, sessions
from daemon.mcp_server import (
    broadcast_status,
    build_agent_options,
    open_file_on_surface,
    record_activity,
)

log = logging.getLogger(__name__)


class ReviewRunner(Protocol):
    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None: ...


def _review_prompt(session_id: str, base_ref: str) -> str:
    return (
        f"Review the code changes in this worktree against the base ref `{base_ref}`. "
        f"Start by running `git diff {base_ref}...HEAD` to see what changed, then read "
        "the surrounding code as needed. For each issue you find, call the "
        "mcp__cvi__upsert_finding tool with these arguments: "
        f'session_id="{session_id}", the `file` path, a short `title`, a `body` '
        "explaining the issue, and a `severity` of high, medium, or low. Where you can, "
        "include an `anchor` of the relevant snippet and line range. This is a "
        "read-only review — do not edit any files. When you have reported every finding, "
        "stop."
    )


async def _log_activity(session_id: str, message: object) -> None:
    """Relay session activity to the daemon terminal (headless but never invisible)
    AND to the surface's live feed, so a watching browser sees what Claude is doing
    as it happens. The terminal log stays authoritative; record_activity buffers +
    broadcasts each line."""
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                log.info("[review %s] %s", session_id, block.text)
                await record_activity(session_id, "text", block.text)
            elif isinstance(block, ToolUseBlock):
                log.info("[review %s] tool: %s", session_id, block.name)
                await record_activity(session_id, "tool", block.name)
    elif isinstance(message, ResultMessage):
        log.info(
            "[review %s] result: subtype=%s is_error=%s",
            session_id,
            message.subtype,
            message.is_error,
        )
        await record_activity(session_id, "result", f"{message.subtype}")


async def _open_first_finding(session_id: str) -> None:
    """Auto-open the first (oldest) finding's file so the surface lands on real
    code when opened, instead of a blank pane. Best-effort: a failure here must
    not fail a review that otherwise succeeded."""
    try:
        rows = await asyncio.to_thread(findings.list_findings, session_id)
        if not rows:
            return
        first = rows[0]
        anchor = first.get("anchor")
        line_range = anchor["range"] if anchor else None
        await open_file_on_surface(session_id, first["file"], line_range)
    except Exception:
        log.warning("auto-open first finding failed for session %s", session_id, exc_info=True)


class AgentReviewRunner:
    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None:
        log.info(
            "starting review for session %s (worktree=%s, base=%s)",
            session_id,
            worktree_path,
            base_ref,
        )
        try:
            options = build_agent_options(cwd=worktree_path)
            async with ClaudeSDKClient(options=options) as client:
                await client.query(_review_prompt(session_id, base_ref))
                async for message in client.receive_response():
                    await _log_activity(session_id, message)
            await _open_first_finding(session_id)
            await asyncio.to_thread(sessions.set_status, session_id, "ready")
            await broadcast_status(session_id, "ready")
            log.info("review complete for session %s", session_id)
        except Exception:
            # Fail-open: a failed run marks the session and must not propagate out
            # of the fire-and-forget task or take down the daemon.
            log.warning("review failed for session %s", session_id, exc_info=True)
            await asyncio.to_thread(sessions.set_status, session_id, "error")
            await broadcast_status(session_id, "error")


# The active runner. Tests inject a fake via daemon.review_runner.runner.
runner: ReviewRunner = AgentReviewRunner()
