"""resolve_base_ref prefers a fresher origin/<branch> when one exists locally,
and falls back defensively otherwise. Exercised against throwaway git repos built
under tmp_path (no network)."""

import subprocess

from daemon.gitref import resolve_base_ref


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _init_repo_with_commit(path):
    """A repo with one (empty) commit on a default branch; returns the HEAD sha."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "commit", "--allow-empty", "-q", "-m", "init")
    out = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _set_remote_tracking(path, branch, sha):
    """Create a remote-tracking ref without a real remote (no network)."""
    _git(path, "update-ref", f"refs/remotes/origin/{branch}", sha)


async def test_prefers_origin_branch_when_it_exists(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo)
    _set_remote_tracking(repo, "main", sha)

    assert await resolve_base_ref(str(repo), "main") == "origin/main"


async def test_is_generic_over_branch_name(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo)
    _set_remote_tracking(repo, "develop", sha)

    assert await resolve_base_ref(str(repo), "develop") == "origin/develop"


async def test_falls_back_when_no_origin_counterpart(tmp_path):
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo)  # local-only, no remote-tracking refs

    assert await resolve_base_ref(str(repo), "main") == "main"


async def test_falls_back_for_a_non_git_directory(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert await resolve_base_ref(str(plain), "main") == "main"
