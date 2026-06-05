import pytest
from fastapi.testclient import TestClient

from daemon.main import app
from daemon.view_state import store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def test_dev_emit_invokes_a_view_control_primitive():
    surface = "emit-surface"
    with TestClient(app) as client:
        response = client.post(
            "/dev/emit", json={"tool": "split_pane", "args": {"surface": surface, "n": 3}}
        )
    assert response.status_code == 200
    assert store.snapshot(surface)["panes"] == 3


def test_dev_emit_404s_on_unknown_primitive():
    with TestClient(app) as client:
        response = client.post("/dev/emit", json={"tool": "nope", "args": {}})
    assert response.status_code == 404
