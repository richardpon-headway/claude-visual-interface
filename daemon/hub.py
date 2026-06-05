"""WebSocket fan-out hub: the daemon's push side of the live stream.

Browsers subscribe per surface; a view-control primitive (or, later, a session's
token stream) broadcasts an event to everyone watching that surface. The daemon is
a single asyncio process, so the registry is a plain in-memory dict — no lock is
needed; broadcast snapshots the subscriber set before iterating so a connection
that leaves mid-broadcast doesn't corrupt the loop.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Sender(Protocol):
    """The slice of WebSocket the hub depends on (lets tests pass a fake)."""

    async def send_json(self, data: Any) -> None: ...


class Hub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Sender]] = {}

    def register(self, surface: str, ws: Sender) -> None:
        self._subscribers.setdefault(surface, set()).add(ws)

    def unregister(self, surface: str, ws: Sender) -> None:
        subscribers = self._subscribers.get(surface)
        if subscribers is None:
            return
        subscribers.discard(ws)
        if not subscribers:
            del self._subscribers[surface]

    def subscriber_count(self, surface: str) -> int:
        return len(self._subscribers.get(surface, ()))

    async def broadcast(self, surface: str, event: dict[str, Any]) -> None:
        # Snapshot first: a send may fail and unregister mid-loop.
        for ws in list(self._subscribers.get(surface, ())):
            try:
                await ws.send_json(event)
            except Exception:
                # Fail-open: a dead socket is expected, not on-call-worthy. Drop it.
                log.debug("dropping unreachable subscriber on surface %s", surface)
                self.unregister(surface, ws)


# The daemon owns a single hub for the whole process.
hub = Hub()
