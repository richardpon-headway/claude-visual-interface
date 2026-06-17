"""CVI daemon entry point.

A manually-started local FastAPI daemon. It owns the SQLite DB, the MCP render
vocabulary, the live view-state store, the WebSocket push hub, and the Agent SDK
chat sessions. Start it with ``make run``; all activity streams in that terminal.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from daemon import sessions
from daemon.agent_session import ImageInput, agents
from daemon.db import apply_migrations
from daemon.hub import hub
from daemon.mcp_server import SERVER_NAME, TOOLS, hydrate_surface
from daemon.view_state import store

_TOOLS_BY_NAME = {t.name: t for t in TOOLS}

HOST = "127.0.0.1"
PORT = 47825

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await apply_migrations()
    log.info("MCP server '%s' ready with %d primitive(s)", SERVER_NAME, len(TOOLS))
    yield
    await agents.shutdown_all()


app = FastAPI(title="Claude Visual Interface", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sessions")
async def get_sessions(include_archived: bool = False) -> dict[str, Any]:
    """List sessions for the home page (newest activity first). Soft-deleted
    sessions are excluded; archived ones unless asked."""
    rows = await asyncio.to_thread(sessions.list_sessions, include_archived=include_archived)
    return {"sessions": rows}


async def _toggle_lifecycle(fn: Any, session_id: str, value: bool) -> dict[str, bool]:
    changed = await asyncio.to_thread(fn, session_id, value)
    if not changed:
        raise HTTPException(status_code=404, detail=f"no session with id {session_id}")
    return {"ok": True}


@app.post("/sessions/{session_id}/archive")
async def archive_session(session_id: str) -> dict[str, bool]:
    return await _toggle_lifecycle(sessions.set_archived, session_id, True)


@app.post("/sessions/{session_id}/unarchive")
async def unarchive_session(session_id: str) -> dict[str, bool]:
    return await _toggle_lifecycle(sessions.set_archived, session_id, False)


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    """Soft-delete (recoverable): hide the session from the default list."""
    return await _toggle_lifecycle(sessions.set_deleted, session_id, True)


@app.post("/sessions/{session_id}/restore")
async def restore_session(session_id: str) -> dict[str, bool]:
    return await _toggle_lifecycle(sessions.set_deleted, session_id, False)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """A single session row, for a browser's initial load (it reads `status` to
    seed the chip; live transitions then arrive as `status` events over the
    WebSocket). 404 when the session doesn't exist."""
    session = await asyncio.to_thread(sessions.get_session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no session with id {session_id}")
    return session


class ChatRequest(BaseModel):
    title: str | None = None


@app.post("/chats")
async def create_chat(req: ChatRequest | None = None) -> dict[str, str]:
    """Create a chat session and return its id. The body is optional
    (a titleless 'New chat'); the browser navigates to the surface and the
    conversation starts on the first message over the WebSocket."""
    title = req.title if req else None
    session_id = await asyncio.to_thread(sessions.create_chat_session, title)
    return {"session_id": session_id}


class EmitRequest(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


@app.post("/dev/emit")
async def dev_emit(req: EmitRequest) -> dict[str, Any]:
    """Dev harness: invoke an MCP primitive by name so the push→render path can be
    exercised by hand — e.g. ``curl`` an ``open_code`` while a browser watches
    ``/ws/<surface>`` — without a real Claude session."""
    tool = _TOOLS_BY_NAME.get(req.tool)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown primitive: {req.tool}")
    return await tool.handler(req.args)


@app.websocket("/ws/{surface}")
async def ws_surface(websocket: WebSocket, surface: str) -> None:
    """Subscribe a browser to a surface's live stream.

    On connect the client gets the current view-state snapshot so it can render
    immediately; thereafter it receives view-control events as they happen. The
    only inbound message is the browser reporting its left-pane selection, which
    the daemon stores so the pull primitives can read it back.
    """
    await websocket.accept()
    hub.register(surface, websocket)
    # Load any persisted transcript before snapshotting so a conversation that
    # outlived a daemon restart replays on connect (no-op after the first connect).
    await hydrate_surface(surface)
    await websocket.send_json(
        {"type": "snapshot", "surface": surface, "payload": store.snapshot(surface)}
    )
    try:
        while True:
            await _handle_inbound(surface, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(surface, websocket)


def _parse_image(raw: Any) -> ImageInput | None:
    """Validate an optional pasted image from a `message` frame — untrusted external
    input. Returns None when absent, and fails closed (None + a warning) when
    malformed: requires a string `media_type` starting `image/` and a non-empty
    string `data` (raw base64)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        log.warning("ignoring image payload: not an object")
        return None
    media_type = raw.get("media_type")
    data = raw.get("data")
    if (
        isinstance(media_type, str)
        and media_type.startswith("image/")
        and isinstance(data, str)
        and data
    ):
        return ImageInput(media_type=media_type, data=data)
    log.warning("ignoring image payload: bad media_type or data")
    return None


async def _stop_surface(surface: str) -> None:
    """Stop whatever the agent is doing on this surface by interrupting the live
    chat turn. A no-op when idle, so a stray Stop is harmless."""
    await agents.interrupt(surface)


async def _handle_inbound(surface: str, raw: str) -> None:
    """Apply a browser→daemon frame. `message` routes a chat turn to the surface's
    live agent session; `stop` aborts the agent's current work on the surface.
    Anything malformed or unknown is ignored (the socket stays open)."""
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return
    if not isinstance(msg, dict):
        return
    msg_type = msg.get("type")
    if msg_type == "stop":  # no payload — applies to whatever is running
        await _stop_surface(surface)
        return
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        return
    if msg_type == "message":
        raw_text = payload.get("text")
        text = raw_text.strip() if isinstance(raw_text, str) else ""
        image = _parse_image(payload.get("image"))
        if text or image is not None:
            await agents.send(surface, text, image=image)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    import uvicorn

    log.info("listening on http://%s:%d", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
