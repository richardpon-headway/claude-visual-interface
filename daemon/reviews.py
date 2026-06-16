"""Start a review: create the session row, then hand off to the runner.

The handoff is fire-and-forget — the review streams for as long as it takes, so
``POST /reviews`` returns the session id immediately and the run proceeds in the
background. No concurrency cap: a second review on the same worktree is just
another independent session.
"""

from __future__ import annotations

import asyncio

from daemon import review_runner, sessions

# Strong references to in-flight runs, keyed by session id so a run can be found
# and cancelled (Stop). create_task only holds a weak ref, so an untracked task
# could be garbage-collected mid-run. The done-callback removes each task once it
# finishes.
_running: dict[str, asyncio.Task[None]] = {}


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
    _running[session_id] = task
    task.add_done_callback(lambda _t: _running.pop(session_id, None))
    return session_id


def cancel(session_id: str) -> bool:
    """Cancel an in-flight run for this session, if one is running. The runner
    catches the cancellation and marks the session 'stopped'. A no-op (returns
    False) when nothing is running for the session."""
    task = _running.get(session_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True
