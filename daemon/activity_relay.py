"""Relay a Claude Agent SDK message to the daemon terminal and the surface feed.

Used by the long-lived conversational session (`agent_session`). Each streamed
message becomes a terminal log line (headless but never invisible) and an activity
entry buffered + broadcast to the surface (PR #20), so the activity feed reads as a
live transcript.
"""

from __future__ import annotations

import logging

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from daemon.mcp_server import record_activity

log = logging.getLogger(__name__)

# Cap a tool summary so one call (a long Bash command, a big input dict) can't
# blow up a feed row.
_MAX_SUMMARY = 120


def _truncate(text: str, limit: int = _MAX_SUMMARY) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_tool_use(block: ToolUseBlock) -> str:
    """A one-line "what this tool call is doing" for the activity feed: the tool
    name (any mcp__server__ prefix stripped) plus a short digest of its key argument.
    The render_html body is deliberately never echoed — only its title — so a big
    HTML page can't flood the feed."""
    name = block.name.split("__")[-1]  # mcp__cvi__render_html -> render_html
    args = block.input if isinstance(block.input, dict) else {}

    if name == "render_html":
        title = args.get("title")
        detail = f"→ {title}" if title else ""
    elif name == "Grep":
        where = args.get("path") or args.get("glob")
        detail = f"{args.get('pattern', '')} in {where}" if where else str(args.get("pattern", ""))
    elif name == "Bash":
        detail = str(args.get("command", ""))
    elif name in ("Read", "Glob"):
        detail = str(args.get("file_path") or args.get("path") or args.get("pattern") or "")
    else:
        detail = ", ".join(f"{k}={v}" for k, v in args.items())

    return _truncate(f"{name} {detail}".strip())


async def _relay_ask(session_id: str, block: ToolUseBlock) -> None:
    """Record an AskUserQuestion call as a structured `ask` entry the browser renders
    as a selectable picker. Carries the tool-use id (echoed back when answering) and the
    `questions` payload; the text is a plain fallback for any non-picker renderer."""
    args = block.input if isinstance(block.input, dict) else {}
    questions = args.get("questions") or []
    first = questions[0].get("question", "") if questions else ""
    fallback = _truncate(f"AskUserQuestion: {first}".strip())
    log.info("[chat %s] ask: %s", session_id, fallback)
    await record_activity(session_id, "ask", fallback, ask_id=block.id, questions=questions)


async def relay_message_activity(
    session_id: str, message: object, background: bool = False
) -> None:
    """Log a streamed agent message and push it to the surface as activity. `background`
    marks segments from an agent-initiated (background-task) turn so the browser can flag
    them as not-a-reply-to-your-prompt."""
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                log.info("[chat %s] %s", session_id, block.text)
                await record_activity(session_id, "text", block.text, background=background)
            elif isinstance(block, ToolUseBlock):
                if block.name.split("__")[-1] == "AskUserQuestion":
                    await _relay_ask(session_id, block)
                else:
                    summary = summarize_tool_use(block)
                    log.info("[chat %s] tool: %s", session_id, summary)
                    await record_activity(session_id, "tool", summary, background=background)
    elif isinstance(message, ResultMessage):
        log.info(
            "[chat %s] result: subtype=%s is_error=%s",
            session_id,
            message.subtype,
            message.is_error,
        )
        await record_activity(
            session_id, "result", f"{message.subtype}", background=background
        )
