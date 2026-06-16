import asyncio

import pytest
from fastapi.testclient import TestClient

from daemon import review_runner, reviews, sessions
from daemon.db import apply_migrations_sync
from daemon.main import app
from daemon.reviews import cancel, start_review


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.ran = asyncio.Event()

    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None:
        self.calls.append(
            {"session_id": session_id, "worktree_path": worktree_path, "base_ref": base_ref}
        )
        self.ran.set()


def test_post_reviews_creates_a_running_review_session(monkeypatch):
    monkeypatch.setattr(review_runner, "runner", FakeRunner())
    with TestClient(app) as client:
        response = client.post("/reviews", json={"worktree_path": "/tmp/wt", "base_ref": "main"})

    assert response.status_code == 200
    session_id = response.json()["session_id"]
    row = sessions.get_session(session_id)
    assert row is not None
    assert row["type"] == "review"
    assert row["status"] == "running"
    assert row["worktree_path"] == "/tmp/wt"
    assert row["base_ref"] == "main"


async def test_start_review_hands_off_to_the_runner(monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(review_runner, "runner", fake)

    session_id = await start_review(worktree_path="/tmp/wt", base_ref="dev")
    await asyncio.wait_for(fake.ran.wait(), 1.0)

    assert fake.calls == [
        {"session_id": session_id, "worktree_path": "/tmp/wt", "base_ref": "dev"}
    ]


class BlockingRunner:
    """A runner that blocks until cancelled, to exercise Stop."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, *, session_id: str, worktree_path: str, base_ref: str) -> None:
        self.started.set()
        await asyncio.Event().wait()  # never completes on its own


async def test_cancel_aborts_an_in_flight_run(monkeypatch):
    monkeypatch.setattr(review_runner, "runner", BlockingRunner())

    session_id = await start_review(worktree_path="/tmp/wt", base_ref="main")
    await asyncio.wait_for(review_runner.runner.started.wait(), 1.0)
    task = reviews._running[session_id]

    assert cancel(session_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    await asyncio.sleep(0)  # let the done-callback deregister the task
    assert session_id not in reviews._running

    # Cancelling again — nothing is running now — is a no-op.
    assert cancel(session_id) is False
    assert cancel("never-started") is False
