"""The CVI MCP server: the render vocabulary a Claude session pushes through.

The daemon hosts a single in-process MCP server (via the Claude Agent SDK) that a
session connects to. A surface is one scrolling conversation; the agent renders
content into it with one primitive:

- render_html — a self-contained HTML page, inline in the conversation

It appends a segment to the per-surface activity buffer and broadcasts it to the
browser over the WebSocket; the buffer rides the connect snapshot for late joiners.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    create_sdk_mcp_server,
    tool,
)

from daemon.hub import hub
from daemon.view_state import store

SERVER_NAME = "cvi"
SERVER_VERSION = "0.1.0"


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


# --- render helpers ---------------------------------------------------------------

async def render_html_on_surface(surface: str, html: str, title: str | None = None) -> None:
    """Render a model-authored HTML page as an inline artifact block in the
    conversation stream: it rides the activity buffer (and the connect snapshot) and
    appears in order, like any other turn. The canonical effect behind render_html."""
    await record_activity(surface, "artifact", title or "", html=html)


async def record_activity(
    surface: str, kind: str, text: str, html: str | None = None
):
    """Append a conversation segment on a surface and push it to subscribers; return
    the stored entry (callers that need to enrich it later — e.g. a prompt's summary —
    hold the reference). `html` carries an artifact's page; it's omitted from the
    payload otherwise."""
    entry = store.append_activity(surface, kind, text, html)
    payload: dict[str, Any] = {"kind": kind, "text": text}
    if html is not None:
        payload["html"] = html
    await hub.broadcast(
        surface,
        {"type": "activity", "surface": surface, "payload": payload},
    )
    return entry


async def broadcast_prompt_summary(surface: str, index: int, summary: str) -> None:
    """Push a generated one-line summary for the index-th user prompt so the outline
    rail's label updates live. The summary is also set on the stored prompt entry by
    the caller, so it rides the connect snapshot for a browser that joins later."""
    await hub.broadcast(
        surface,
        {
            "type": "prompt_summary",
            "surface": surface,
            "payload": {"index": index, "text": summary},
        },
    )


async def broadcast_status(surface: str, status: str) -> None:
    """Push a session status change (running → ready / error) to subscribers so the
    surface's status chip flips live. Status itself is persisted on the session row;
    this is the transient nudge to connected browsers."""
    await hub.broadcast(
        surface,
        {"type": "status", "surface": surface, "payload": {"status": status}},
    )


async def broadcast_title(surface: str, title: str) -> None:
    """Push a generated session title to subscribers so the surface header updates
    live. Like broadcast_status, this is pure-broadcast: the title is persisted on the
    session row and seeded into a connecting browser via GET /sessions/{id}, so it
    doesn't ride the ViewState connect snapshot."""
    await hub.broadcast(
        surface,
        {"type": "title", "surface": surface, "payload": {"title": title}},
    )


async def broadcast_thinking(surface: str, active: bool) -> None:
    """Flip the surface's in-flight 'thinking' flag and push it to subscribers so the
    chat shows/hides its thinking indicator. Unlike status, this has no DB home, so
    it's stored on the ViewState to ride the connect snapshot (mirrors activity)."""
    store.set_thinking(surface, active)
    await hub.broadcast(
        surface,
        {"type": "thinking", "surface": surface, "payload": {"active": active}},
    )


# --- render primitives ------------------------------------------------------------

@tool(
    "render_html",
    "Render a self-contained HTML page inline in the conversation — for anything "
    "visual that isn't code: a design, diagram, table, report, or text-driven review. "
    "Each call appears as its own block in the conversation. Emit self-contained "
    "HTML/CSS/SVG only — no JavaScript and no external/CDN resources (the page renders "
    "in a no-script sandbox).",
    {
        "type": "object",
        "properties": {
            "surface": {"type": "string", "description": "Surface UUID to route to"},
            "html": {"type": "string", "description": "A complete, self-contained HTML document"},
            "title": {"type": "string", "description": "Short label for the page (optional)"},
        },
        "required": ["surface", "html"],
    },
)
async def render_html(args: dict[str, Any]) -> dict[str, Any]:
    surface = args["surface"]
    await render_html_on_surface(surface, args["html"], args.get("title"))
    return _ok(f"rendered html on surface {surface}")


# The full primitive vocabulary: render content into the conversation.
TOOLS = [
    render_html,
]

TOOL_NAMES = [t.name for t in TOOLS]

# Fully-qualified names the Agent SDK exposes to a session: mcp__<server>__<tool>.
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES]

cvi_server = create_sdk_mcp_server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    tools=TOOLS,
)


# Built-in tools a review session needs to inspect the checkout (read + git),
# auto-approved alongside the cvi primitives. Edit/Write are intentionally absent:
# a review is read-only (applying fixes is a later phase).
REVIEW_TOOLS = ["Read", "Grep", "Glob", "Bash"]

_REVIEW_APPROVED = frozenset([*ALLOWED_TOOLS, *REVIEW_TOOLS])


async def _approve_read_only_tools(
    tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    """Headless permission gate: approve the review tool set, deny everything else
    (e.g. Edit/Write). Keeps an unattended review read-only and never blocks on an
    interactive prompt."""
    if tool_name in _REVIEW_APPROVED:
        return PermissionResultAllow()
    return PermissionResultDeny(message="CVI review sessions are read-only")


# The render contract: visuals render inline in the conversation as self-contained
# no-script pages. Kept as one constant so the chat prompt's rule can't drift.
_RENDER_HTML_GUIDANCE = (
    "For anything visual — a design, diagram, table, chart, or report — use "
    "mcp__cvi__render_html to render a full HTML page inline in the conversation. That "
    "page must be self-contained HTML/CSS/SVG only: no JavaScript and no external/CDN "
    "resources, as it renders in a no-script sandbox. Render rather than only describe "
    "when the user asks to see something."
)

# The framing for a conversational session — the system prompt every chat agent runs.
CVI_CHAT_SYSTEM_PROMPT = (
    "You are a Claude session with a visual surface: a single conversation the user "
    "reads top to bottom, where your answers, rendered HTML pages, and file diffs all "
    f"appear inline. {_RENDER_HTML_GUIDANCE} This is a read-only session — do not edit "
    "files."
)


def build_agent_options(
    cwd: str | Path | None = None,
    system_prompt: str | None = None,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    """Build the session-connection point: options that attach the CVI MCP server
    and pre-approve its primitives plus the read-only review tools. Pass `cwd` to
    run the session against a review worktree, `system_prompt` to steer an
    interactive session (the one-shot runner leaves it None), and `resume` with a
    prior SDK session id to continue that conversation (chat resuming a review)."""
    return ClaudeAgentOptions(
        mcp_servers={SERVER_NAME: cvi_server},
        allowed_tools=[*ALLOWED_TOOLS, *REVIEW_TOOLS],
        can_use_tool=_approve_read_only_tools,
        cwd=cwd,
        system_prompt=system_prompt,
        resume=resume,
    )
