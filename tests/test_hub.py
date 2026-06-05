from typing import Any

from daemon.hub import Hub


class FakeWS:
    def __init__(self, *, fail: bool = False) -> None:
        self.received: list[Any] = []
        self.fail = fail

    async def send_json(self, data: Any) -> None:
        if self.fail:
            raise ConnectionError("socket closed")
        self.received.append(data)


async def test_broadcast_reaches_only_subscribers_of_that_surface():
    hub = Hub()
    a = FakeWS()
    b = FakeWS()
    hub.register("s1", a)
    hub.register("s2", b)

    await hub.broadcast("s1", {"type": "open_code"})

    assert a.received == [{"type": "open_code"}]
    assert b.received == []


async def test_unregister_stops_delivery():
    hub = Hub()
    ws = FakeWS()
    hub.register("s", ws)
    hub.unregister("s", ws)
    assert hub.subscriber_count("s") == 0

    await hub.broadcast("s", {"type": "split_pane"})
    assert ws.received == []


async def test_broadcast_drops_a_dead_subscriber():
    hub = Hub()
    live = FakeWS()
    dead = FakeWS(fail=True)
    hub.register("s", live)
    hub.register("s", dead)

    await hub.broadcast("s", {"type": "show_diff"})

    assert live.received == [{"type": "show_diff"}]
    assert hub.subscriber_count("s") == 1  # dead socket was unregistered
