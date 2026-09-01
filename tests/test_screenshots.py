import base64
import io

import pytest
from PIL import Image

from daemon import screenshots
from daemon.agent_session import ImageInput


@pytest.fixture(autouse=True)
def screenshots_dir(tmp_path, monkeypatch):
    # get_screenshots_dir() derives from the DB path's parent, so pointing CVI_DB_PATH at
    # a temp dir isolates the screenshots dir too — no migrations needed.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))


def _png_b64(width: int, height: int) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_persist_downscales_large_image_to_webp():
    [name] = screenshots.persist_images([ImageInput("image/png", _png_b64(4000, 3000))])
    assert name.endswith(".webp") and len(name) == 37
    with Image.open(screenshots.get_screenshots_dir() / name) as out:
        assert out.format == "WEBP"
        assert max(out.size) == 1600  # longest edge capped


def test_persist_does_not_upscale_a_small_image():
    [name] = screenshots.persist_images([ImageInput("image/png", _png_b64(200, 100))])
    with Image.open(screenshots.get_screenshots_dir() / name) as out:
        assert out.size == (200, 100)  # unchanged — thumbnail never upscales


def test_persist_skips_a_bad_image_but_keeps_the_rest():
    good = ImageInput("image/png", _png_b64(50, 50))
    bad = ImageInput("image/png", base64.b64encode(b"not an image").decode())
    names = screenshots.persist_images([good, bad, good])
    assert len(names) == 2


def test_persist_empty_returns_empty():
    assert screenshots.persist_images([]) == []


def test_resolve_rejects_traversal_and_malformed_names():
    assert screenshots.resolve_screenshot_path("../cvi.db") is None
    assert screenshots.resolve_screenshot_path("evil.png") is None
    assert screenshots.resolve_screenshot_path("not-a-uuid.webp") is None
    # Well-formed name, but no such file on disk.
    assert screenshots.resolve_screenshot_path("a" * 32 + ".webp") is None


def test_resolve_accepts_an_existing_file():
    [name] = screenshots.persist_images([ImageInput("image/png", _png_b64(50, 50))])
    assert screenshots.resolve_screenshot_path(name) == screenshots.get_screenshots_dir() / name
