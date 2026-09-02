"""On-disk store for user-uploaded screenshots.

Pasted/dropped images are downscaled and written here as WebP files; only their
filenames are persisted on the message row (see `messages.py` `images`). Keeping the
bytes on disk — not in the DB — keeps rows small and the pre-migration DB snapshots
text-only. The dir sits next to `cvi.db`, so a `CVI_DB_PATH` override relocates it too.

The model still receives the full-resolution image (the daemon downscales only the copy
it writes here), so stored-copy fidelity is deliberately secondary to keeping the dir
small.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from daemon.db import get_db_path

if TYPE_CHECKING:
    from daemon.agent_session import ImageInput

log = logging.getLogger(__name__)

# Longest-edge cap for the stored copy; only shrinks (Image.thumbnail never upscales).
_MAX_EDGE = 1600
_WEBP_QUALITY = 80

# A stored screenshot filename: a uuid4 hex + ".webp". The serve route accepts only names
# matching this, so a value can't smuggle in "../" traversal or an unexpected extension.
_NAME_RE = re.compile(r"^[0-9a-f]{32}\.webp$")


def get_screenshots_dir() -> Path:
    """The dir holding downscaled screenshots, next to cvi.db (honors CVI_DB_PATH)."""
    return get_db_path().parent / "screenshots"


def persist_images(images: list[ImageInput]) -> list[str]:
    """Downscale each image and write it as ``<uuid>.webp`` under the screenshots dir;
    return the filenames written, in order. One bad image is skipped (and logged) rather
    than sinking the batch, so a partial batch persists what it can and a total failure
    returns ``[]``."""
    if not images:
        return []
    dest_dir = get_screenshots_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for image in images:
        try:
            names.append(_write_one(image, dest_dir))
        except Exception:
            # A single unreadable/oversized image shouldn't drop the whole turn's batch;
            # the transcript degrades gracefully for whatever didn't persist.
            log.warning("failed to persist a screenshot; skipping it", exc_info=True)
    return names


def _write_one(image: ImageInput, dest_dir: Path) -> str:
    raw = base64.b64decode(image.data)
    with Image.open(io.BytesIO(raw)) as src:
        # WebP handles RGB/RGBA; convert anything else (palette, grayscale, CMYK) to RGB.
        img = src if src.mode in ("RGB", "RGBA") else src.convert("RGB")
        img.thumbnail((_MAX_EDGE, _MAX_EDGE))  # in place, preserves aspect, never upscales
        name = f"{uuid.uuid4().hex}.webp"
        img.save(dest_dir / name, format="WEBP", quality=_WEBP_QUALITY)
    return name


def resolve_screenshot_path(name: str) -> Path | None:
    """Map a screenshot filename (a serve-route path segment) to its on-disk path, or
    None if the name is malformed or the file is missing. The regex is the path-traversal
    guard: only a bare uuid4-hex ``.webp`` name is accepted, so ``../``, absolute paths,
    and other extensions are rejected before any filesystem access."""
    if not _NAME_RE.match(name):
        return None
    path = get_screenshots_dir() / name
    return path if path.is_file() else None
