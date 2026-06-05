"""CVI daemon entry point.

A manually-started local FastAPI daemon. It owns the SQLite DB, the MCP render
vocabulary, the live view-state store, and the WebSocket push hub (and, in a later
phase, the Agent SDK review sessions). Start it with ``make run``; all activity
streams in that terminal.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from daemon.db import apply_migrations
from daemon.hub import hub
from daemon.mcp_server import SERVER_NAME, TOOLS
from daemon.view_state import store

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


@app.websocket("/ws/{surface}")
async def ws_surface(websocket: WebSocket, surface: str) -> None:
    """Subscribe a browser to a surface's live stream.

    On connect the client gets the current view-state snapshot so it can render
    immediately; thereafter it receives view-control events as they happen. There
    is no inbound protocol yet (selection reporting lands with the pull
    primitives) — reads only keep the socket open and detect close.
    """
    await websocket.accept()
    hub.register(surface, websocket)
    await websocket.send_json(
        {"type": "snapshot", "surface": surface, "payload": store.snapshot(surface)}
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(surface, websocket)


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
