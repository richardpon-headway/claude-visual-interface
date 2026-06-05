"""Start a review: create the session row, then hand off to the runner.

The handoff is fire-and-forget — the review streams for as long as it takes, so
``POST /reviews`` returns the session id immediately and the run proceeds in the
background. No concurrency cap: a second review on the same worktree is just
another independent session.
"""

from __future__ import annotations

import asyncio

from daemon import review_runner, sessions

# Strong references to in-flight runs; create_task only holds a weak ref, so an
# untracked task could be garbage-collected mid-run. The done-callback removes
# each task once it finishes.
_running: set[asyncio.Task[None]] = set()


async def start_review(
    *,
    worktree_path: str,
    base_ref: str,
    repo: str | None = None,
    branch: str | None = None,
    title: str | None = None,
) -> str:
    session_id = await asyncio.to_thread(
        sessions.create_review_session,
        worktree_path=worktree_path,
        base_ref=base_ref,
        repo=repo,
        branch=branch,
        title=title,
    )
    task = asyncio.create_task(
        review_runner.runner.run(
            session_id=session_id, worktree_path=worktree_path, base_ref=base_ref
        )
    )
    _running.add(task)
    task.add_done_callback(_running.discard)
    return session_id
