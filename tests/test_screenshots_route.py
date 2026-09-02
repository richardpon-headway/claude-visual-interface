import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from daemon import screenshots
from daemon.agent_session import ImageInput
from daemon.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    # The lifespan runs migrations on startup; point them (and the derived screenshots
    # dir) at a temp location.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (1, 2, 3)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_get_screenshot_serves_the_webp():
    [name] = screenshots.persist_images([ImageInput("image/png", _png_b64())])
    with TestClient(app) as client:
        resp = client.get(f"/screenshots/{name}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content[:4] == b"RIFF"  # WebP container magic


def test_get_screenshot_404_for_missing_file():
    with TestClient(app) as client:
        resp = client.get("/screenshots/" + "a" * 32 + ".webp")
    assert resp.status_code == 404


def test_get_screenshot_404_for_malformed_name():
    with TestClient(app) as client:
        assert client.get("/screenshots/evil.png").status_code == 404
        assert client.get("/screenshots/not-a-uuid.webp").status_code == 404
