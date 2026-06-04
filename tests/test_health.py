import pytest
from fastapi.testclient import TestClient

from daemon.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    # The lifespan runs migrations on startup; point them at a temp DB.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
