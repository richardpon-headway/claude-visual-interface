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

from daemon import config, sessions
from daemon.agent_session import ImageInput, agents
from daemon.db import apply_migrations
from daemon.hub import hub
from daemon.mcp_server import SERVER_NAME, TOOLS, broadcast_title, hydrate_surface
from daemon.view_state import store

_TOOLS_BY_NAME = {t.name: t for t in TOOLS}

HOST = "127.0.0.1"
PORT = 47825

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await apply_migrations()
    config.ensure_config_file()
    log.info("chat working_dir = %s", config.get_working_dir())
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


class RenameRequest(BaseModel):
    title: str


@app.post("/sessions/{session_id}/rename")
async def rename_session(session_id: str, req: RenameRequest) -> dict[str, bool]:
    """Set a user-provided title override on a session. The override wins over the
    auto-generated title on every surface and survives the periodic title refresh.
    422 on an empty/whitespace title; 404 when the session doesn't exist."""
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be empty")
    changed = await asyncio.to_thread(sessions.set_user_title, session_id, title)
    if not changed:
        raise HTTPException(status_code=404, detail=f"no session with id {session_id}")
    await broadcast_title(session_id, title)
    return {"ok": True}


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


@app.post("/chats/open")
async def open_chat() -> dict[str, str]:
    """The chat to open on launch: reuse the newest empty 'New chat' if one exists,
    else create one. Lets the root route drop straight into a chat without piling up
    empty sessions on every launch."""
    session_id = await asyncio.to_thread(sessions.open_or_create_chat)
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
    try:
        # Load any persisted transcript before snapshotting so a conversation that
        # outlived a daemon restart replays on connect (no-op after the first connect).
        # The snapshot send is inside the try so a client that vanishes mid-connect
        # (a quick refresh) is handled like any disconnect — no unhandled error, and
        # the finally still unregisters the dead socket.
        await hydrate_surface(surface)
        await websocket.send_json(
            {"type": "snapshot", "surface": surface, "payload": store.snapshot(surface)}
        )
        while True:
            await _handle_inbound(surface, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(surface, websocket)


# Cap on images per turn. base64 inflates ~33%, so this keeps a realistic batch of
# screenshots inline on the `message` frame under uvicorn's 16 MB WebSocket limit;
# mirrors the front-end's cap.
_MAX_IMAGES_PER_TURN = 8


def _parse_image(raw: Any) -> ImageInput | None:
    """Validate one pasted image dict — untrusted external input. Returns None when it's
    not a well-formed image: requires a string `media_type` starting `image/` and a
    non-empty string `data` (raw base64)."""
    if not isinstance(raw, dict):
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
    return None


def _parse_images(raw: Any) -> list[ImageInput]:
    """Validate a list of pasted images from a `message` frame — untrusted external
    input. Returns [] when absent; otherwise keeps each well-formed image in order,
    dropping malformed entries (fail closed per element) and capping at
    _MAX_IMAGES_PER_TURN. A single warning fires when anything is dropped."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        log.warning("ignoring images payload: not a list")
        return []
    images = [img for img in (_parse_image(item) for item in raw) if img is not None]
    if len(images) < len(raw):
        log.warning("dropped %d malformed image(s) from payload", len(raw) - len(images))
    if len(images) > _MAX_IMAGES_PER_TURN:
        log.warning(
            "capping %d images to %d per turn", len(images), _MAX_IMAGES_PER_TURN
        )
        images = images[:_MAX_IMAGES_PER_TURN]
    return images


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
        # Prefer the new `images` list; fall back to a legacy single `image` key so an
        # old front-end bundle keeps working until it rebuilds to send `images`.
        if "images" in payload:
            images = _parse_images(payload.get("images"))
        else:
            legacy = _parse_image(payload.get("image"))
            images = [legacy] if legacy is not None else []
        if text or images:
            await agents.send(surface, text, images=images)
    elif msg_type == "answer":
        ask_id = payload.get("id")
        answer = payload.get("answer")
        if isinstance(ask_id, str) and isinstance(answer, str) and answer:
            await agents.answer(surface, ask_id, answer)


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
