"""Relay a Claude Agent SDK message to the daemon terminal and the surface feed.

Shared by both agent loops: the one-shot review runner (`review_runner`) and the
long-lived conversational session (`agent_session`). Each streamed message becomes
a terminal log line (headless but never invisible) and an activity entry buffered +
broadcast to the surface (PR #20), so the activity feed reads as a live transcript.
"""

from __future__ import annotations

import logging

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from daemon.mcp_server import record_activity

log = logging.getLogger(__name__)


async def relay_message_activity(session_id: str, message: object) -> None:
    """Log a streamed agent message and push it to the surface as activity."""
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
