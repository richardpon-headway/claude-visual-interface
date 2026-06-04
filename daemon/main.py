"""CVI daemon entry point.

A manually-started local FastAPI daemon. It owns the SQLite DB (and, in later
phases, the MCP server and the Agent SDK sessions). Start it with ``make run``;
all activity streams in that terminal.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from daemon.db import apply_migrations

HOST = "127.0.0.1"
PORT = 47825

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await apply_migrations()
    yield


app = FastAPI(title="Claude Visual Interface", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
