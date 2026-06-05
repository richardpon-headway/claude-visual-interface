import pytest
from fastapi.testclient import TestClient

from daemon.hub import hub
from daemon.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    # The lifespan runs migrations on startup; point them at a temp DB.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def test_ws_sends_a_snapshot_on_connect_and_registers_then_cleans_up():
    surface = "ws-route"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{surface}") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert first["surface"] == surface
            assert first["payload"]["surface"] == surface
            assert hub.subscriber_count(surface) == 1

    # The connection closed, so the hub dropped the subscriber.
    assert hub.subscriber_count(surface) == 0
