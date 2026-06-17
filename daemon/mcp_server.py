"""The CVI MCP server: the typed render vocabulary a Claude session pushes through.

The daemon hosts a single in-process MCP server (via the Claude Agent SDK) that a
session connects to. Its tools are a small, curated set of typed primitives — NOT
arbitrary HTML — namespaced by direction:

- view-control (transient): open_code / split_pane / highlight_range / show_diff / render_html
- state (persisted):         upsert_finding / set_disposition / anchor_message
- pull (read):               get_selection / get_view_state

This phase registers the vocabulary and the session-connection point. The handlers
are stubs: they accept and echo their arguments but do not yet update daemon state
or push to the browser — that wiring (DB + WebSocket) lands in a later phase.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolAnnotations,
    ToolPermissionContext,
    create_sdk_mcp_server,
    tool,
)

from daemon import findings
from daemon.hub import hub
from daemon.view_state import store

SERVER_NAME = "cvi"
SERVER_VERSION = "0.1.0"

# A line range within a file, 1-based and inclusive. Reused by several primitives.
_RANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {"type": "integer", "description": "1-based start line"},
        "end": {"type": "integer", "description": "1-based end line, inclusive"},
    },
    "required": ["start", "end"],
}


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _not_wired(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Stub result for an unwired primitive — echoes the call for observability."""
    text = f"[cvi skeleton] {name} accepted {args!r}; state/render wiring lands in a later phase."
    return _ok(text)


# --- view-control primitives (transient) -----------------------------------------

async def open_file_on_surface(
    surface: str, file: str, line_range: dict[str, int] | None = None, pane: int = 0
) -> None:
    """Open a file in a surface's left pane: update the view store and push the
    open_code event to subscribers. The canonical effect behind the open_code
    primitive — also called by the review runner to auto-open a finding's file."""
    store.open_code(surface, file, line_range, pane)
    await hub.broadcast(
        surface,
        {"type": "open_code", "surface": surface,
         "payload": {"file": file, "range": line_range, "pane": pane}},
    )


async def render_html_on_surface(surface: str, html: str, title: str | None = None) -> None:
    """Render a model-authored HTML page as an inline artifact block in the
    conversation stream: it rides the activity buffer (and the connect snapshot) and
    appears in order, like any other turn. The canonical effect behind render_html."""
    await record_activity(surface, "artifact", title or "", html=html)


async def record_activity(surface: str, kind: str, text: str, html: str | None = None):
    """Append a conversation segment on a surface and push it to subscribers; return
    the stored entry (callers that need to enrich it later — e.g. a prompt's summary —
    hold the reference). `html` carries the page for an artifact segment; it's omitted
    from the payload otherwise."""
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


@tool(
    "open_code",
    "Open a file in the review's left pane, optionally scrolled to a line range and "
    "targeted at a specific split pane. Omit 'range' to open at the top; omit 'pane' "
    "to use the primary pane.",
    {
        "type": "object",
        "properties": {
            "surface": {"type": "string", "description": "Surface UUID to route to"},
            "file": {"type": "string", "description": "Repo-relative file path"},
            "range": _RANGE_SCHEMA,
            "pane": {"type": "integer", "description": "0-based split-pane index"},
        },
        "required": ["surface", "file"],
    },
)
async def open_code(args: dict[str, Any]) -> dict[str, Any]:
    surface = args["surface"]
    file = args["file"]
    pane = args.get("pane", 0)
    await open_file_on_surface(surface, file, args.get("range"), pane)
    return _ok(f"opened {file} on surface {surface} (pane {pane})")


@tool(
    "split_pane",
    "Split the left pane of a surface into n independent, side-by-side code views.",
    {"surface": str, "n": int},
)
async def split_pane(args: dict[str, Any]) -> dict[str, Any]:
    surface = args["surface"]
    n = args["n"]
    store.split_pane(surface, n)
    await hub.broadcast(
        surface, {"type": "split_pane", "surface": surface, "payload": {"n": n}}
    )
    return _ok(f"split surface {surface} into {n} pane(s)")


@tool(
    "highlight_range",
    "Highlight a line range in a file on the left pane of a surface.",
    {
        "type": "object",
        "properties": {
            "surface": {"type": "string", "description": "Surface UUID to route to"},
            "file": {"type": "string", "description": "Repo-relative file path"},
            "range": _RANGE_SCHEMA,
        },
        "required": ["surface", "file", "range"],
    },
)
async def highlight_range(args: dict[str, Any]) -> dict[str, Any]:
    surface = args["surface"]
    file = args["file"]
    line_range = args["range"]
    store.highlight_range(surface, file, line_range)
    await hub.broadcast(
        surface,
        {"type": "highlight_range", "surface": surface,
         "payload": {"file": file, "range": line_range}},
    )
    return _ok(f"highlighted {file} {line_range} on surface {surface}")


@tool(
    "show_diff",
    "Render a current-vs-proposed diff on a surface. 'a' and 'b' are content "
    "references (e.g. 'current' or a suggested-patch id).",
    {"surface": str, "a": str, "b": str},
)
async def show_diff(args: dict[str, Any]) -> dict[str, Any]:
    surface = args["surface"]
    a = args["a"]
    b = args["b"]
    store.show_diff(surface, a, b)
    await hub.broadcast(
        surface, {"type": "show_diff", "surface": surface, "payload": {"a": a, "b": b}}
    )
    return _ok(f"showing diff {a} vs {b} on surface {surface}")


@tool(
    "render_html",
    "Render a self-contained HTML page on the left pane of a surface — for anything "
    "visual that isn't code: a design, diagram, table, report, or text-driven review. "
    "A later render_html replaces the page; opening a code file switches the pane back "
    "to the code view. Emit self-contained HTML/CSS/SVG only — no JavaScript and no "
    "external/CDN resources (the page renders in a no-script sandbox).",
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


# --- state primitives (persisted) -------------------------------------------------

@tool(
    "upsert_finding",
    "Create or update a code-anchored review finding. Pass 'id' to update an "
    "existing finding; omit it to create one.",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Finding id; omit to create"},
            "session_id": {"type": "string", "description": "Owning session UUID"},
            "file": {"type": "string", "description": "Repo-relative file path"},
            "anchor": {
                "type": "object",
                "description": "Quoted snippet + line range for fuzzy relocation",
                "properties": {
                    "snippet": {"type": "string"},
                    "range": _RANGE_SCHEMA,
                },
            },
            "severity": {"type": "string", "description": "Finding severity"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "suggested_patch": {"type": "string"},
            "source_lens": {"type": "string", "description": "Which review lens produced it"},
            "actions": {"type": "array", "items": {"type": "string"}},
            "disposition": {"type": "string"},
        },
        "required": ["session_id", "file", "title", "body"],
    },
)
async def upsert_finding(args: dict[str, Any]) -> dict[str, Any]:
    try:
        finding_id = await asyncio.to_thread(
            findings.upsert_finding,
            finding_id=args.get("id"),
            session_id=args["session_id"],
            file=args["file"],
            title=args["title"],
            body=args["body"],
            severity=args.get("severity"),
            anchor=args.get("anchor"),
            suggested_patch=args.get("suggested_patch"),
            source_lens=args.get("source_lens"),
            actions=args.get("actions"),
        )
    except findings.UnknownSessionError:
        return {
            "content": [{"type": "text", "text": f"no session with id {args['session_id']}"}],
            "is_error": True,
        }
    finding = await asyncio.to_thread(findings.get_finding, finding_id)
    if finding is not None:
        surface = finding["session_id"]
        await hub.broadcast(surface, {"type": "finding", "surface": surface, "payload": finding})
    return _ok(json.dumps({"finding_id": finding_id}))


@tool(
    "set_disposition",
    "Set the disposition of a finding (e.g. dismiss / fix / defer).",
    {"finding_id": str, "value": str},
)
async def set_disposition(args: dict[str, Any]) -> dict[str, Any]:
    finding_id = args["finding_id"]
    value = args["value"]
    surface = await asyncio.to_thread(findings.set_disposition, finding_id, value)
    if surface is None:
        return {
            "content": [{"type": "text", "text": f"no finding with id {finding_id}"}],
            "is_error": True,
        }
    await hub.broadcast(
        surface,
        {
            "type": "disposition",
            "surface": surface,
            "payload": {"finding_id": finding_id, "value": value},
        },
    )
    return _ok(f"set disposition of {finding_id} to {value}")


@tool(
    "anchor_message",
    "Anchor a conversation message to a file range so the panes stay in sync.",
    {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Message id to anchor"},
            "file": {"type": "string", "description": "Repo-relative file path"},
            "range": _RANGE_SCHEMA,
        },
        "required": ["message_id", "file", "range"],
    },
)
async def anchor_message(args: dict[str, Any]) -> dict[str, Any]:
    return _not_wired("anchor_message", args)


# --- pull primitives (read) -------------------------------------------------------

@tool(
    "get_selection",
    "Read the user's current left-pane selection on a surface.",
    {"surface": str},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def get_selection(args: dict[str, Any]) -> dict[str, Any]:
    return _ok(json.dumps({"selection": store.snapshot(args["surface"])["selection"]}))


@tool(
    "get_view_state",
    "Read the current view state (open files, splits, highlights) of a surface.",
    {"surface": str},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def get_view_state(args: dict[str, Any]) -> dict[str, Any]:
    return _ok(json.dumps(store.snapshot(args["surface"])))


# The full primitive vocabulary, in push-then-pull order.
TOOLS = [
    open_code,
    split_pane,
    highlight_range,
    show_diff,
    render_html,
    upsert_finding,
    set_disposition,
    anchor_message,
    get_selection,
    get_view_state,
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


# The HTML-canvas contract both prompts share: render visuals as a full, self-
# contained page in the no-script sandbox. Kept as one constant so the rule can't
# drift between the chat and review framings.
_RENDER_HTML_GUIDANCE = (
    "For anything visual — a design, diagram, table, chart, or report — use "
    "mcp__cvi__render_html to render a full HTML page on the left pane. That page "
    "must be self-contained HTML/CSS/SVG only: no JavaScript and no external/CDN "
    "resources, as it renders in a no-script sandbox. Render rather than only "
    "describe when the user asks to see something."
)

# The general framing for a conversational session: a chat on the right with an
# HTML canvas on the left. The default the chat agent passes for a non-review surface.
CVI_CHAT_SYSTEM_PROMPT = (
    "You are a Claude session with a visual surface. The user types in a right-hand "
    "conversation pane and you reply there in text. You also have an HTML canvas on "
    f"the left. {_RENDER_HTML_GUIDANCE} This is a read-only session — do not edit files."
)

# The review specialization: same canvas, plus the code-review primitives. The
# one-shot runner omits this (its review prompt is self-contained); the chat agent
# passes it when continuing a review conversation.
CVI_REVIEW_SYSTEM_PROMPT = (
    "You are operating a visual code-review surface. The user watches a left code "
    "pane and a right conversation pane. Use the cvi tools to drive the left pane: "
    "mcp__cvi__open_code to show a file (optionally at a line range), "
    "mcp__cvi__highlight_range to point at lines, and mcp__cvi__upsert_finding to "
    "record a review finding anchored to code. When the user asks you to look at or "
    f"show something, open it in the pane rather than only describing it. {_RENDER_HTML_GUIDANCE} "
    "This is a read-only session — do not edit files."
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
