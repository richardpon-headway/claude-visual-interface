"""CVI daemon entry point.

A manually-started local FastAPI daemon. It owns the SQLite DB, the MCP render
vocabulary, the live view-state store, and the WebSocket push hub (and, in a later
phase, the Agent SDK review sessions). Start it with ``make run``; all activity
streams in that terminal.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from daemon import reviews
from daemon.db import apply_migrations
from daemon.hub import hub
from daemon.mcp_server import SERVER_NAME, TOOLS
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


app = FastAPI(title="Claude Visual Interface", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class ReviewRequest(BaseModel):
    worktree_path: str
    base_ref: str
    repo: str | None = None
    branch: str | None = None
    title: str | None = None


@app.post("/reviews")
async def create_review(req: ReviewRequest) -> dict[str, str]:
    """Create a review session over a worktree and kick off the run. Returns the
    session id; the run proceeds in the background and streams over its WebSocket."""
    session_id = await reviews.start_review(
        worktree_path=req.worktree_path,
        base_ref=req.base_ref,
        repo=req.repo,
        branch=req.branch,
        title=req.title,
    )
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
    await websocket.send_json(
        {"type": "snapshot", "surface": surface, "payload": store.snapshot(surface)}
    )
    try:
        while True:
            _apply_inbound(surface, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(surface, websocket)


def _apply_inbound(surface: str, raw: str) -> None:
    """Apply a browser→daemon frame. Only `selection` is understood; anything
    malformed or unknown is ignored (the socket stays open)."""
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return
    if not isinstance(msg, dict) or msg.get("type") != "selection":
        return
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        return
    file = payload.get("file")
    line_range = payload.get("range")
    if isinstance(file, str) and isinstance(line_range, dict):
        store.set_selection(surface, file, line_range)


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
