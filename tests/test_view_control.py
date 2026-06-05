"""The view-control primitives mutate the live store AND push over the hub."""

from typing import Any

from daemon.hub import hub
from daemon.mcp_server import highlight_range, open_code, show_diff, split_pane
from daemon.view_state import store


class FakeWS:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def send_json(self, data: Any) -> None:
        self.received.append(data)


async def test_open_code_updates_store_and_broadcasts():
    surface = "vc-open"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await open_code.handler(
            {"surface": surface, "file": "a.py", "range": {"start": 1, "end": 4}, "pane": 0}
        )
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).open[0].file == "a.py"
    assert ws.received == [
        {
            "type": "open_code",
            "surface": surface,
            "payload": {"file": "a.py", "range": {"start": 1, "end": 4}, "pane": 0},
        }
    ]


async def test_split_pane_broadcasts_event():
    surface = "vc-split"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await split_pane.handler({"surface": surface, "n": 3})
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).panes == 3
    assert ws.received == [{"type": "split_pane", "surface": surface, "payload": {"n": 3}}]


async def test_highlight_range_broadcasts_event():
    surface = "vc-highlight"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await highlight_range.handler(
            {"surface": surface, "file": "a.py", "range": {"start": 7, "end": 9}}
        )
    finally:
        hub.unregister(surface, ws)

    assert ws.received[0]["type"] == "highlight_range"
    assert ws.received[0]["payload"] == {"file": "a.py", "range": {"start": 7, "end": 9}}


async def test_show_diff_broadcasts_event():
    surface = "vc-diff"
    ws = FakeWS()
    hub.register(surface, ws)
    try:
        await show_diff.handler({"surface": surface, "a": "current", "b": "patch-1"})
    finally:
        hub.unregister(surface, ws)

    assert store.get_or_create(surface).diff.a == "current"
    assert ws.received == [
        {"type": "show_diff", "surface": surface, "payload": {"a": "current", "b": "patch-1"}}
    ]
