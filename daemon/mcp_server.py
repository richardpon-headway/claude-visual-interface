"""The CVI MCP server: the render vocabulary a Claude session pushes through.

The daemon hosts a single in-process MCP server (via the Claude Agent SDK) that a
session connects to. A surface is one scrolling conversation; the agent renders
content into it with one primitive:

- render_html — a self-contained HTML page, inline in the conversation

It appends a segment to the per-surface activity buffer and broadcasts it to the
browser over the WebSocket; the buffer rides the connect snapshot for late joiners.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    tool,
)

from daemon import messages, token_usage
from daemon.hub import hub
from daemon.view_state import ActivityEntry, store

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


async def hydrate_surface(surface: str) -> None:
    """Load a surface's persisted transcript into the live store on first connect, so
    the connect snapshot replays a conversation that outlived a daemon restart. A
    no-op after the first call this process run (idempotent across reconnects), and it
    marks the surface hydrated even when empty so a reconnect won't re-query the DB or
    clobber entries recorded live since."""
    if store.is_hydrated(surface):
        return
    rows = await asyncio.to_thread(messages.list_messages, surface)
    store.load_activity(
        surface,
        [
            ActivityEntry(
                kind=row["kind"],
                text=row["text"],
                html=row["html"],
                summary=row["summary"],
                message_id=row["id"],
            )
            for row in rows
        ],
    )
    store.mark_hydrated(surface)
    # Rebuild the running token total from the persisted per-call rows, so the footer
    # counter is correct after a daemon restart (before any new turns accumulate).
    out, inp = await asyncio.to_thread(token_usage.session_totals, surface)
    store.seed_tokens(surface, out, inp)


async def record_activity(
    surface: str,
    kind: str,
    text: str,
    html: str | None = None,
    ask_id: str | None = None,
    questions: list | None = None,
):
    """Append a conversation segment on a surface and push it to subscribers; return
    the stored entry (callers that need to enrich it later — e.g. a prompt's summary —
    hold the reference). `html` carries an artifact's page; `ask_id`/`questions` carry an
    AskUserQuestion picker's payload; each is omitted from the broadcast otherwise."""
    entry = store.append_activity(surface, kind, text, html, ask_id, questions)
    # Write the segment through to SQLite so the transcript survives a daemon
    # restart; hold the row id on the entry so a later summary can target it. (The
    # structured `questions` aren't persisted — a restarted picker falls back to text.)
    entry.message_id = await asyncio.to_thread(
        messages.append_message, surface, kind, text, html
    )
    payload: dict[str, Any] = {"kind": kind, "text": text}
    if html is not None:
        payload["html"] = html
    if ask_id is not None:
        payload["ask_id"] = ask_id
    if questions is not None:
        payload["questions"] = questions
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


async def broadcast_answer(surface: str, ask_id: str, answer: str) -> None:
    """Record a picker's chosen value on its `ask` entry and push it to subscribers so
    the picker locks to the answered state live. Stored on the ViewState (like the
    prompt summary) so it rides the connect snapshot for a browser that reloads."""
    store.set_answer(surface, ask_id, answer)
    await hub.broadcast(
        surface,
        {"type": "answer", "surface": surface, "payload": {"id": ask_id, "answer": answer}},
    )


async def broadcast_tokens(surface: str, output_tokens: int, input_tokens: int) -> None:
    """Add one LLM call's tokens to the surface's running session total and push the new
    total to subscribers so the footer counter updates live. Like the thinking flag, the
    total has no DB home of its own (it's summed from token_usage on hydration), so it's
    held on the ViewState to ride the connect snapshot."""
    total_out, total_in = store.add_tokens(surface, output_tokens, input_tokens)
    await hub.broadcast(
        surface,
        {
            "type": "tokens",
            "surface": surface,
            "payload": {"output": total_out, "input": total_in},
        },
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


# The render contract: visuals render inline in the conversation as self-contained
# no-script pages. Kept as one constant so the chat prompt's rule can't drift.
_RENDER_HTML_GUIDANCE = (
    "For anything visual — a design, diagram, table, chart, or report — use "
    "mcp__cvi__render_html to render a full HTML page inline in the conversation. That "
    "page must be self-contained HTML/CSS/SVG only: no JavaScript and no external/CDN "
    "resources, as it renders in a no-script sandbox. Render rather than only describe "
    "when the user asks to see something. "
    "The app renders your page on a dark surface at the app's scale automatically, so: "
    "do NOT set a light/white page background and do NOT add CSS zoom (either would "
    "fight the app). Author reading and explanatory content for dark — light text on "
    "the dark surface, with darker panels/borders for structure. The one exception is a "
    "UI mockup that must show its own real colors: set data-theme=\"light\" on the root "
    "<html> to opt out of the dark surface and render the mockup in its intended "
    "palette. Convention for framing content: a blue left-rule marks something you're "
    "telling the user, an amber left-rule marks a question you're asking."
)

# The framing for a conversational session — the system prompt every chat agent runs.
CVI_CHAT_SYSTEM_PROMPT = (
    "You are a Claude session with a visual surface: a single conversation the user "
    "reads top to bottom, where your answers and rendered HTML pages appear inline. "
    f"{_RENDER_HTML_GUIDANCE} You can read and edit files and run commands, just like "
    "any Claude session."
)


def build_agent_options(
    cwd: str | Path | None = None,
    system_prompt: str | None = None,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    """Build the session-connection point: options that attach the CVI MCP server and
    grant full read/write tool access. A daemon session is headless (no interactive
    permission prompts), so `bypassPermissions` is the equivalent of the CLI's
    accept-all. `cwd` is the directory the session runs in (chat sessions pass the
    configured `working_dir`; defaults to None so the SDK inherits the process cwd);
    `system_prompt` steers the session; `resume` carries a prior SDK session id to
    continue that conversation."""
    return ClaudeAgentOptions(
        mcp_servers={SERVER_NAME: cvi_server},
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=cwd,
        system_prompt=system_prompt,
        resume=resume,
    )
