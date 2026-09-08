"""The CVI render vocabulary a Claude session drives through its reply text.

A surface is one scrolling conversation. Rather than call a tool, the agent renders
a page by wrapping self-contained HTML in a `<cvi-artifact>` tag in its normal reply;
the relay (see `activity_relay.split_render_segments`) sniffs that tag out of the
streamed text and calls `render_html_on_surface` here. Using no tool keeps the render
path off the MCP surface entirely — nothing to gate, so it survives a session that has
already touched a PHI-class MCP tool.

The render effect appends a segment to the per-surface activity buffer and broadcasts
it to the browser over the WebSocket; the buffer rides the connect snapshot for late
joiners. This module also owns the chat system prompt and the session-options builder.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from daemon import config, messages, token_usage
from daemon.hub import hub
from daemon.mcp_auth import remote_auth
from daemon.view_state import ActivityEntry, store

log = logging.getLogger(__name__)


# --- render helpers ---------------------------------------------------------------

async def render_html_on_surface(
    surface: str, html: str, title: str | None = None, background: bool = False
) -> None:
    """Render a model-authored HTML page as an inline artifact block in the
    conversation stream: it rides the activity buffer (and the connect snapshot) and
    appears in order, like any other turn. The canonical render effect, called by the
    relay when it sniffs a `<cvi-artifact>` tag out of the model's reply text.
    `background` marks a page produced by an agent-initiated (background-task) turn."""
    await record_activity(surface, "artifact", title or "", html=html, background=background)


def _entry_from_row(row: dict[str, Any]) -> ActivityEntry:
    """Rebuild an ActivityEntry from a persisted `message` row. A picker row carries
    its structured payload ({ask_id, questions}) as JSON in `data` and its chosen value
    in `answer`, so a reloaded picker re-renders rich and, if answered, locked. The
    `background` flag (0/1) is restored so an agent-initiated segment reloads dimmed +
    tagged rather than as a foreground reply."""
    ask_id: str | None = None
    questions: list | None = None
    raw = row.get("data")
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            ask_id = payload.get("ask_id")
            questions = payload.get("questions")
    images: list[str] | None = None
    raw_images = row.get("images")
    if raw_images:
        try:
            parsed = json.loads(raw_images)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            images = parsed
    return ActivityEntry(
        kind=row["kind"],
        text=row["text"],
        html=row["html"],
        summary=row["summary"],
        background=bool(row.get("background")),
        message_id=row["id"],
        ask_id=ask_id,
        questions=questions,
        answer=row.get("answer"),
        images=images,
    )


async def hydrate_surface(surface: str) -> None:
    """Load a surface's persisted transcript into the live store on first connect, so
    the connect snapshot replays a conversation that outlived a daemon restart. A
    no-op after the first call this process run (idempotent across reconnects), and it
    marks the surface hydrated even when empty so a reconnect won't re-query the DB or
    clobber entries recorded live since."""
    if store.is_hydrated(surface):
        return
    rows = await asyncio.to_thread(messages.list_messages, surface)
    store.load_activity(surface, [_entry_from_row(row) for row in rows])
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
    background: bool = False,
    images: list[str] | None = None,
):
    """Append a conversation segment on a surface and push it to subscribers; return
    the stored entry (callers that need to enrich it later — e.g. a prompt's summary —
    hold the reference). `html` carries an artifact's page; `ask_id`/`questions` carry an
    AskUserQuestion picker's payload; `background` marks a segment that belongs to an
    agent-initiated (background-task) turn; `images` carries a user turn's screenshot
    filenames (already written to disk); each is omitted from the broadcast otherwise."""
    entry = store.append_activity(
        surface, kind, text, html, ask_id, questions, background, images
    )
    # Write the segment through to SQLite so the transcript survives a daemon restart;
    # hold the row id on the entry so a later summary (or a picker answer) can target it.
    # A picker's structured payload (its tool-use id + `questions`, including each
    # option's rich HTML preview) is persisted as JSON so a restarted picker re-renders
    # rich instead of falling back to text. `images` is stored the same way — a JSON list
    # of screenshot filenames — so a reloaded user turn re-renders its thumbnails.
    data = (
        json.dumps({"ask_id": ask_id, "questions": questions})
        if ask_id is not None or questions is not None
        else None
    )
    images_json = json.dumps(images) if images else None
    entry.message_id = await asyncio.to_thread(
        messages.append_message, surface, kind, text, html, data, images_json, background
    )
    payload: dict[str, Any] = {"kind": kind, "text": text}
    if html is not None:
        payload["html"] = html
    if ask_id is not None:
        payload["ask_id"] = ask_id
    if questions is not None:
        payload["questions"] = questions
    if background:
        payload["background"] = True
    if images:
        payload["images"] = images
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


async def broadcast_title(surface: str, title: str) -> None:
    """Push a generated session title to subscribers so the surface header updates
    live. Pure-broadcast: the title is persisted on the session row and seeded into a
    connecting browser via GET /sessions/{id}, so it doesn't ride the ViewState connect
    snapshot."""
    await hub.broadcast(
        surface,
        {"type": "title", "surface": surface, "payload": {"title": title}},
    )


async def broadcast_answer(surface: str, ask_id: str, answer: str) -> None:
    """Record a picker's chosen value on its `ask` entry and push it to subscribers so
    the picker locks to the answered state live. Held on the ViewState (so it rides the
    connect snapshot for a browser that reloads) and written through to the picker's
    message row (so an answered picker re-renders locked after a daemon restart)."""
    entry = store.set_answer(surface, ask_id, answer)
    if entry is not None and entry.message_id is not None:
        await asyncio.to_thread(messages.set_message_answer, entry.message_id, answer)
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


# The render contract: visuals render inline in the conversation as self-contained
# no-script pages. Kept as one constant so the chat prompt's rule can't drift.
_RENDER_HTML_GUIDANCE = (
    "Default to rendering an HTML page rather than answering in prose. Any output that "
    "has structure — a design, diagram, table, chart, or report, but also a comparison, "
    "a list, ranked or trade-off options, a step-by-step explanation, a summary of "
    "findings, or a walkthrough of code or a decision — should be an inline HTML page, "
    "not plain text. To render a page, wrap the complete HTML document in a "
    "<cvi-artifact> tag: <cvi-artifact title=\"Short label\">…your HTML…</cvi-artifact> "
    "(the title is optional). Everything between the tags is rendered inline as a "
    "self-contained page; any text outside the tags is shown as normal prose, so you "
    "may precede a page with a one-line pointer. Use the <cvi-artifact> tag ONLY to "
    "render a page for the user to see — when you instead want to SHOW HTML source as "
    "an example (teaching, quoting code), put it in a normal ```html code block, which "
    "is never rendered. Reserve plain prose for genuinely "
    "conversational replies: a short direct answer, a quick acknowledgement, or a "
    "clarifying question. When it's a close call, render. That "
    "page must be self-contained HTML/CSS/SVG only: no JavaScript and no external/CDN "
    "resources, as it renders in a no-script sandbox. Always render rather than only "
    "describe when the user asks to see something. "
    "The app renders your page on a dark surface at the app's scale automatically, so: "
    "do NOT set a light/white page background and do NOT add CSS zoom (either would "
    "fight the app). Author reading and explanatory content for dark — light text on "
    "the dark surface, with darker panels/borders for structure. The one exception is a "
    "UI mockup that must show its own real colors: set data-theme=\"light\" on the root "
    "<html> to opt out of the dark surface and render the mockup in its intended "
    "palette. Convention for framing content: a blue left-rule marks something you're "
    "telling the user, an amber left-rule marks a question you're asking. "
    "A rendered page is the single place its content lives: do NOT also restate it "
    "in prose. Keep any accompanying text to a one-line pointer, or nothing — never "
    "echo the rendered page back as a plain-text answer."
)

# The picker contract: a multiple-choice decision goes through AskUserQuestion, and
# each option may carry a rich HTML preview rendered inline beside a Select button — so
# the options appear once, in the picker, never also as a rendered page or a text list.
_ASK_PICKER_GUIDANCE = (
    "When you need the user to choose between options, use the AskUserQuestion tool "
    "rather than listing the choices in prose. Each option may carry a rich HTML "
    "`preview`: a self-contained HTML/CSS/SVG fragment (same rules as a rendered page — "
    "no JavaScript, no external/CDN resources, no CSS zoom, authored for the dark "
    "surface) that renders inline in the picker beside a Select button the user clicks. "
    "Put an option's full detail in its preview and lead the preview with the option's "
    "label so the card's heading matches the choice. Do NOT also render the same options "
    "as a <cvi-artifact> page or repeat them as a text list — the picker is the single "
    "place the options appear."
)

# The framing for a conversational session — the system prompt every chat agent runs.
CVI_CHAT_SYSTEM_PROMPT = (
    "You are a Claude session with a visual surface: a single conversation the user "
    "reads top to bottom, where your answers and rendered HTML pages appear inline. "
    f"{_RENDER_HTML_GUIDANCE} {_ASK_PICKER_GUIDANCE} You can read and edit files and run "
    "commands, just like any Claude session."
)


def build_agent_options(
    cwd: str | Path | None = None,
    system_prompt: str | None = None,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    """Build the session-connection point: options that grant full read/write tool
    access and attach any external MCP servers. Rendering is no longer a tool — the
    session renders by emitting a `<cvi-artifact>` tag in its reply text — so CVI
    contributes no in-process server here. A daemon session is headless (no interactive
    permission prompts), so `bypassPermissions` is the equivalent of the CLI's
    accept-all. `cwd` is the directory the session runs in (chat sessions pass the
    configured `working_dir`; defaults to None so the SDK inherits the process cwd);
    `system_prompt` steers the session; `resume` carries a prior SDK session id to
    continue that conversation.

    External MCP servers declared in `config.yaml` (`mcp_servers`) are attached, each
    with a matching `allowed_tools` entry so its tools are actually usable. A plain local
    server is attached as its stdio spec. A remote OAuth server is attached *directly* at
    its `url` over its `transport`, with the current token from its shared auth keeper
    (`daemon.mcp_auth`) injected as an `Authorization` header — so the session never
    spawns its own `mcp-remote`. A remote server whose keeper hasn't authenticated yet is
    omitted this build (and logged); the next session respawn picks it up once a token
    exists. `strict_mcp_config` keeps the server set fully determined by CVI's config —
    no ambient CLI/project config is merged in."""
    servers: dict[str, dict[str, object]] = {}
    for name, spec in config.get_mcp_servers().items():
        if spec.get("type") == "remote":
            token = remote_auth.token_for(name)
            if token is None:
                # Expected while a keeper is still doing its cold-start OAuth; this runs on
                # every session build, so keep it at debug — the keeper's own lifecycle
                # logs carry the actionable signal.
                log.debug(
                    "MCP server %r has no auth token yet; omitting from this session",
                    name,
                    extra={"server": name},
                )
                continue
            servers[name] = {
                "type": spec["transport"],
                "url": spec["url"],
                "headers": {"Authorization": f"Bearer {token}"},
            }
        else:
            servers[name] = spec
    return ClaudeAgentOptions(
        mcp_servers=servers,
        allowed_tools=[f"mcp__{name}" for name in servers],
        strict_mcp_config=True,
        permission_mode="bypassPermissions",
        cwd=cwd,
        system_prompt=system_prompt,
        resume=resume,
    )
