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
    # Isolate config too, so a real config.yaml at the repo root can't leak external
    # MCP servers into these assertions. Tests that need servers write their own.
    monkeypatch.setenv("CVI_CONFIG_PATH", str(tmp_path / "absent-config.yaml"))
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
    # The dark-surface contract must stay in the prompt: agents author for dark, the app
    # owns zoom, and a mockup opts out with the marker.
    assert "dark surface" in CVI_CHAT_SYSTEM_PROMPT
    assert 'data-theme="light"' in CVI_CHAT_SYSTEM_PROMPT


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


def _write_config(tmp_path, monkeypatch, body: str) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body)
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))


def test_build_agent_options_attaches_configured_external_servers(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        "mcp_servers:\n"
        "  cfv:\n"
        "    command: uv\n"
        '    args: ["run", "--directory", "/x/cfv", "python", "-m", "daemon.mcp_server"]\n'
        "  claude-asset-renderer:\n"
        "    command: uv\n"
        '    args: ["run", "--directory", "/x/car", "python", "-m", "daemon.mcp_server"]\n',
    )
    options = build_agent_options()
    assert set(options.mcp_servers) == {SERVER_NAME, "cfv", "claude-asset-renderer"}
    # The in-process cvi server is preserved; externals arrive as stdio specs.
    assert options.mcp_servers[SERVER_NAME] is cvi_server
    assert options.mcp_servers["cfv"]["type"] == "stdio"
    # The allowlist fix: each external server's tools are approved (plus the cvi base).
    assert "mcp__cfv" in options.allowed_tools
    assert "mcp__claude-asset-renderer" in options.allowed_tools
    assert set(ALLOWED_TOOLS).issubset(options.allowed_tools)
    # CVI fully owns its server set — no ambient CLI/project config is merged in.
    assert options.strict_mcp_config is True


def test_build_agent_options_ignores_reserved_cvi_name(tmp_path, monkeypatch):
    _write_config(
        tmp_path,
        monkeypatch,
        "mcp_servers:\n"
        "  cvi:\n"
        "    command: uv\n"
        '    args: ["run", "impostor"]\n',
    )
    options = build_agent_options()
    # A config entry named `cvi` can't shadow the in-process server.
    assert set(options.mcp_servers) == {SERVER_NAME}
    assert options.mcp_servers[SERVER_NAME] is cvi_server


def test_build_agent_options_passes_resume_session_id():
    assert build_agent_options(resume="sdk-xyz").resume == "sdk-xyz"
    assert build_agent_options().resume is None


def test_sessions_have_full_write_access():
    # No read-only gate: a headless chat runs with bypassPermissions (the CLI's
    # accept-all), so reads, edits, and commands are all permitted.
    options = build_agent_options()
    assert options.permission_mode == "bypassPermissions"
    assert options.can_use_tool is None
