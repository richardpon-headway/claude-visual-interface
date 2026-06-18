import pytest
from fastapi.testclient import TestClient

from daemon.main import app
from daemon.view_state import store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def test_dev_emit_renders_html():
    surface = "emit-html"
    with TestClient(app) as client:
        response = client.post(
            "/dev/emit",
            json={"tool": "render_html", "args": {"surface": surface, "html": "<p>hi</p>"}},
        )
    assert response.status_code == 200
    # render_html appends an inline artifact segment to the conversation stream.
    assert store.snapshot(surface)["activity"][-1] == {
        "kind": "artifact",
        "text": "",
        "html": "<p>hi</p>",
        "summary": None,
        "ask_id": None,
        "questions": None,
        "answer": None,
    }


def test_dev_emit_404s_on_unknown_primitive():
    with TestClient(app) as client:
        response = client.post("/dev/emit", json={"tool": "nope", "args": {}})
    assert response.status_code == 404
