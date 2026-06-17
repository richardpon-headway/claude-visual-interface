import pytest

from daemon.db import apply_migrations_sync, open_db
from daemon.mcp_server import (
    ALLOWED_TOOLS,
    CVI_CHAT_SYSTEM_PROMPT,
    SERVER_NAME,
    TOOLS,
    build_agent_options,
    cvi_server,
)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    # Isolate the DB and seed the session that the render primitives target.
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES ('mcp-test', 'chat', 'ready', 't', 't')",
        )
        conn.commit()
    finally:
        conn.close()


EXPECTED_PRIMITIVES = {
    "render_html",
}

# Valid arguments for each primitive, so every handler can be exercised.
VALID_ARGS = {
    "render_html": {"surface": "mcp-test", "html": "<p>hi</p>"},
}


def test_server_registers_the_full_primitive_vocabulary():
    assert {t.name for t in TOOLS} == EXPECTED_PRIMITIVES
    assert cvi_server["type"] == "sdk"
    assert cvi_server["name"] == SERVER_NAME


def test_chat_prompt_drives_the_html_canvas():
    # The chat prompt isn't review-framed but still drives render_html.
    assert "code-review surface" not in CVI_CHAT_SYSTEM_PROMPT
    assert "render_html" in CVI_CHAT_SYSTEM_PROMPT
    assert "no JavaScript" in CVI_CHAT_SYSTEM_PROMPT


def test_allowed_tools_are_fully_qualified():
    assert ALLOWED_TOOLS == [f"mcp__{SERVER_NAME}__{t.name}" for t in TOOLS]


async def test_every_handler_returns_a_content_block():
    for t in TOOLS:
        result = await t.handler(VALID_ARGS[t.name])
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["content"][0]["type"] == "text"


def test_build_agent_options_attaches_server_and_approves_primitives():
    options = build_agent_options()
    assert options.mcp_servers == {SERVER_NAME: cvi_server}
    # The cvi primitives are auto-approved.
    assert set(ALLOWED_TOOLS).issubset(options.allowed_tools)
    assert options.cwd is None


def test_build_agent_options_passes_resume_session_id():
    assert build_agent_options(resume="sdk-xyz").resume == "sdk-xyz"
    assert build_agent_options().resume is None


def test_sessions_have_full_write_access():
    # No read-only gate: a headless chat runs with bypassPermissions (the CLI's
    # accept-all), so reads, edits, and commands are all permitted.
    options = build_agent_options()
    assert options.permission_mode == "bypassPermissions"
    assert options.can_use_tool is None
