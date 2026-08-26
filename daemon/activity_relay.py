"""Relay a Claude Agent SDK message to the daemon terminal and the surface feed.

Used by the long-lived conversational session (`agent_session`). Each streamed
message becomes a terminal log line (headless but never invisible) and an activity
entry buffered + broadcast to the surface (PR #20), so the activity feed reads as a
live transcript.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from daemon.mcp_server import record_activity, render_html_on_surface

log = logging.getLogger(__name__)

# Cap a tool summary so one call (a long Bash command, a big input dict) can't
# blow up a feed row.
_MAX_SUMMARY = 120


@dataclass
class RenderSegment:
    """One ordered piece of a text block: either prose (`kind="text"`) or a page the
    model asked to render (`kind="artifact"`, carrying its `html` and optional `title`)."""

    kind: str
    text: str = ""
    html: str = ""
    title: str = ""


# Left-to-right scanner over a model text block. The alternation order matters: a
# fenced code block and an inline code span are matched (and thus consumed) BEFORE the
# artifact tag, so a `<cvi-artifact>` that appears inside code — a ```html example or a
# `<cvi-artifact>` shown in prose while explaining the feature — is treated as literal
# text and never rendered. A `<cvi-artifact>` with no closing tag simply doesn't match,
# so a truncated page is never rendered either.
_SEGMENT_SCANNER = re.compile(
    r"(?P<fence>```.*?```)"
    r"|(?P<inline>`[^`\n]*`)"
    r"|(?P<artifact><cvi-artifact(?P<attrs>[^>]*)>(?P<html>.*?)</cvi-artifact>)",
    re.DOTALL | re.IGNORECASE,
)
_TITLE_ATTR = re.compile(
    r"""title\s*=\s*(?P<q>["'])(?P<val>.*?)(?P=q)""", re.IGNORECASE
)


def split_render_segments(text: str) -> list[RenderSegment]:
    """Split a model text block into ordered prose/artifact segments. Each
    `<cvi-artifact …>…</cvi-artifact>` (outside any code span) becomes an `artifact`
    segment; the surrounding prose becomes `text` segments, in reading order.
    Whitespace-only prose is dropped. Text with no artifact tag yields at most one
    `text` segment (or none, if blank)."""
    segments: list[RenderSegment] = []
    buf: list[str] = []

    def flush_text() -> None:
        joined = "".join(buf).strip()
        buf.clear()
        if joined:
            segments.append(RenderSegment(kind="text", text=joined))

    pos = 0
    for m in _SEGMENT_SCANNER.finditer(text):
        buf.append(text[pos : m.start()])
        pos = m.end()
        if m.group("artifact") is not None:
            flush_text()
            title_match = _TITLE_ATTR.search(m.group("attrs") or "")
            segments.append(
                RenderSegment(
                    kind="artifact",
                    html=m.group("html").strip(),
                    title=title_match.group("val") if title_match else "",
                )
            )
        else:
            # A code span (fenced or inline) — keep it verbatim as prose.
            buf.append(m.group(0))
    buf.append(text[pos:])
    flush_text()
    return segments


def _truncate(text: str, limit: int = _MAX_SUMMARY) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_tool_use(block: ToolUseBlock) -> str:
    """A one-line "what this tool call is doing" for the activity feed: the tool
    name (any mcp__server__ prefix stripped) plus a short digest of its key argument."""
    name = block.name.split("__")[-1]
    args = block.input if isinstance(block.input, dict) else {}

    if name == "Grep":
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
                # Sniff the reply for `<cvi-artifact>` pages and emit them as artifacts;
                # everything else stays prose. Done here — before any log or persist —
                # so raw HTML never floods the terminal or the text feed.
                for seg in split_render_segments(block.text):
                    if seg.kind == "artifact":
                        detail = f" → {seg.title}" if seg.title else ""
                        log.info("[chat %s] artifact:%s", session_id, detail)
                        await render_html_on_surface(
                            session_id, seg.html, seg.title, background=background
                        )
                    else:
                        log.info("[chat %s] %s", session_id, seg.text)
                        await record_activity(
                            session_id, "text", seg.text, background=background
                        )
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
