"""The CVI MCP server: the typed render vocabulary a Claude session pushes through.

The daemon hosts a single in-process MCP server (via the Claude Agent SDK) that a
session connects to. Its tools are a small, curated set of typed primitives — NOT
arbitrary HTML — namespaced by direction:

- view-control (transient): open_code / split_pane / highlight_range / show_diff
- state (persisted):         upsert_finding / set_disposition / anchor_message
- pull (read):               get_selection / get_view_state

This phase registers the vocabulary and the session-connection point. The handlers
are stubs: they accept and echo their arguments but do not yet update daemon state
or push to the browser — that wiring (DB + WebSocket) lands in a later phase.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ToolAnnotations, create_sdk_mcp_server, tool

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
    line_range = args.get("range")
    pane = args.get("pane", 0)
    store.open_code(surface, file, line_range, pane)
    await hub.broadcast(
        surface,
        {"type": "open_code", "surface": surface,
         "payload": {"file": file, "range": line_range, "pane": pane}},
    )
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
    return _not_wired("upsert_finding", args)


@tool(
    "set_disposition",
    "Set the disposition of a finding (e.g. dismiss / fix / defer).",
    {"finding_id": str, "value": str},
)
async def set_disposition(args: dict[str, Any]) -> dict[str, Any]:
    return _not_wired("set_disposition", args)


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
    return _not_wired("get_selection", args)


@tool(
    "get_view_state",
    "Read the current view state (open files, splits, highlights) of a surface.",
    {"surface": str},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def get_view_state(args: dict[str, Any]) -> dict[str, Any]:
    return _not_wired("get_view_state", args)


# The full primitive vocabulary, in push-then-pull order.
TOOLS = [
    open_code,
    split_pane,
    highlight_range,
    show_diff,
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


def build_agent_options() -> ClaudeAgentOptions:
    """Build the session-connection point: options that attach the CVI MCP server
    and pre-approve its primitives. Later phases extend this with the checkout cwd
    and a review skill."""
    return ClaudeAgentOptions(
        mcp_servers={SERVER_NAME: cvi_server},
        allowed_tools=list(ALLOWED_TOOLS),
    )
