"""upsert_finding / set_disposition push over the hub, and findings load over HTTP."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from daemon.db import apply_migrations_sync, open_db
from daemon.hub import hub
from daemon.main import app
from daemon.mcp_server import set_disposition, upsert_finding

SESSION = "wire-session"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES (?, 'review', 'running', 't', 't')",
            (SESSION,),
        )
        conn.commit()
    finally:
        conn.close()


class FakeWS:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def send_json(self, data: Any) -> None:
        self.received.append(data)


async def test_upsert_finding_broadcasts_to_the_session_surface():
    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await upsert_finding.handler(
            {"session_id": SESSION, "file": "a.py", "title": "leak", "body": "details"}
        )
    finally:
        hub.unregister(SESSION, ws)

    assert len(ws.received) == 1
    event = ws.received[0]
    assert event["type"] == "finding"
    assert event["surface"] == SESSION
    assert event["payload"]["file"] == "a.py"
    assert event["payload"]["title"] == "leak"


async def test_set_disposition_broadcasts_to_the_session_surface():
    created = await upsert_finding.handler(
        {"session_id": SESSION, "file": "a.py", "title": "t", "body": "b"}
    )
    fid = json.loads(created["content"][0]["text"])["finding_id"]

    ws = FakeWS()
    hub.register(SESSION, ws)
    try:
        await set_disposition.handler({"finding_id": fid, "value": "dismissed"})
    finally:
        hub.unregister(SESSION, ws)

    assert ws.received == [
        {
            "type": "disposition",
            "surface": SESSION,
            "payload": {"finding_id": fid, "value": "dismissed"},
        }
    ]


def test_get_findings_returns_the_sessions_findings():
    with TestClient(app) as client:
        client.post(
            "/dev/emit",
            json={
                "tool": "upsert_finding",
                "args": {"session_id": SESSION, "file": "a.py", "title": "t", "body": "b"},
            },
        )
        response = client.get(f"/sessions/{SESSION}/findings")

    assert response.status_code == 200
    findings_list = response.json()["findings"]
    assert len(findings_list) == 1
    assert findings_list[0]["file"] == "a.py"


async def test_upsert_unknown_session_returns_is_error_not_a_crash():
    result = await upsert_finding.handler(
        {"session_id": "nonexistent", "file": "a.py", "title": "t", "body": "b"}
    )
    assert result["is_error"] is True


def test_dev_emit_unknown_session_is_a_clean_200_not_500():
    with TestClient(app) as client:
        resp = client.post(
            "/dev/emit",
            json={
                "tool": "upsert_finding",
                "args": {"session_id": "nonexistent", "file": "a.py", "title": "t", "body": "b"},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["is_error"] is True
