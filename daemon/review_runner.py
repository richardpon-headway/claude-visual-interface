"""The review-run seam.

``POST /reviews`` creates a session row and hands off to a ReviewRunner. The real
runner — spawning a Claude Agent SDK session that runs the review adapter over the
checkout (it inherits the user's Claude Code auth; no alternate key) — needs the
Claude Code CLI, auth, and a worktree, and lands in a later slice. Until then the
placeholder just records the request. Swap ``runner`` to plug in the real
implementation (or a fake, in tests).
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class ReviewRunner(Protocol):
    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None: ...


class PlaceholderRunner:
    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None:
        log.info(
            "review run requested for session %s (worktree=%s, base=%s); "
            "Agent SDK session wiring lands in a later slice",
            session_id,
            worktree_path,
            base_ref,
        )


# The active runner. A later slice replaces this with the Agent SDK implementation.
runner: ReviewRunner = PlaceholderRunner()
