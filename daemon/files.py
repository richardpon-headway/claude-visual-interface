"""Read a file from a session's worktree, safely.

The path arrives from the browser (untrusted), so it is resolved against the
worktree root and rejected if it escapes — via `..`, an absolute path, or a
symlink pointing outside. Binary and oversized files are reported rather than
returned, so the editor degrades cleanly instead of rendering garbage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Cap on what we'll read into a response — large files aren't useful to render
# in the pane and would bloat the payload. Files over this are reported, not sent.
MAX_FILE_BYTES = 1_000_000


class FileOutsideWorktreeError(Exception):
    """The requested path resolves outside the session's worktree."""


@dataclass
class FileResult:
    path: str
    content: str | None
    reason: str | None = None  # "binary" | "too_large" when content is None


def read_worktree_file(worktree_path: str, rel_path: str) -> FileResult | None:
    """Read `rel_path` within `worktree_path`. Returns None if the file doesn't
    exist; raises FileOutsideWorktreeError if the path escapes the worktree."""
    base = Path(worktree_path).resolve()
    # `.resolve()` collapses `..` and follows symlinks, so an escape (relative,
    # absolute, or via symlink) lands outside `base` and is caught here.
    target = (base / rel_path).resolve()
    if not target.is_relative_to(base):
        raise FileOutsideWorktreeError(rel_path)
    if not target.is_file():
        return None

    if target.stat().st_size > MAX_FILE_BYTES:
        return FileResult(path=rel_path, content=None, reason="too_large")

    data = target.read_bytes()
    if b"\x00" in data:
        return FileResult(path=rel_path, content=None, reason="binary")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileResult(path=rel_path, content=None, reason="binary")
    return FileResult(path=rel_path, content=text)
