"""Resolve a review's diff base to a tighter, fresher git ref.

A review reviews a *changeset* — `git diff <base>...HEAD` — so the diff is only
as good as the base commit. Callers pass a branch name (the PR's base, commonly
`main` but maybe `develop` / `release/x`). A *local* branch ref is often stale:
if you branched off a `main` that has since fallen far behind `origin/main`, the
merge-base sits deep in history and the diff balloons to thousands of unrelated
files.

The remote-tracking ref `origin/<branch>` is cached in `.git` (no network) and
usually points at a newer commit — the branch the PR actually targets. Preferring
it as the base keeps the merge-base recent and the diff tight. This is generic
over the branch name; it never assumes `main`.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def resolve_base_ref(worktree_path: str, base_ref: str) -> str:
    """Return a fresher base ref for the diff, preferring `origin/<base_ref>` when
    that remote-tracking ref exists in the worktree. Falls back to `base_ref`
    unchanged for already-qualified refs, SHAs, tags, no-remote repos, and non-git
    directories. Local-only (no fetch); read-only (`rev-parse`). Defensive: any git
    failure logs and returns the caller's ref so base resolution never breaks a
    review."""
    candidate = f"origin/{base_ref}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            worktree_path,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/remotes/{candidate}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await proc.wait()
    except OSError:
        # git missing / worktree path unusable — fail open to the caller's ref.
        log.info("could not run git to resolve base ref %s, using as-is", base_ref)
        return base_ref
    if returncode == 0:
        return candidate
    log.info("base ref %s has no origin counterpart, using as-is", base_ref)
    return base_ref


async def file_diff(worktree_path: str, base_ref: str, path: str) -> str | None:
    """Return the unified diff of `path` between `base_ref` and HEAD (merge-base
    based: `git diff base...HEAD -- path`), or None on any git failure. Read-only;
    `path` is passed after `--` so it can't be read as a revision."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            worktree_path,
            "diff",
            f"{base_ref}...HEAD",
            "--",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
    except OSError:
        log.info("could not run git diff for %s", path)
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode("utf-8", errors="replace")
