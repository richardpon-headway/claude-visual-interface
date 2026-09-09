import pytest

import daemon.mcp_server as mcp_server
from daemon.db import apply_migrations_sync, open_db
from daemon.mcp_server import (
    CVI_CHAT_SYSTEM_PROMPT,
    build_agent_options,
)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    # Isolate the DB and seed the session that the render path targets.
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


def test_chat_prompt_drives_the_render_tag():
    # The chat prompt isn't review-framed but still drives rendering — now via the
    # <cvi-artifact> tag rather than an MCP tool call.
    assert "code-review surface" not in CVI_CHAT_SYSTEM_PROMPT
    assert "<cvi-artifact" in CVI_CHAT_SYSTEM_PROMPT
    assert "mcp__cvi__render_html" not in CVI_CHAT_SYSTEM_PROMPT
    assert "no JavaScript" in CVI_CHAT_SYSTEM_PROMPT
    # The dark-surface contract must stay in the prompt: agents author for dark, the app
    # owns zoom, and a mockup opts out with the marker.
    assert "dark surface" in CVI_CHAT_SYSTEM_PROMPT
    assert 'data-theme="light"' in CVI_CHAT_SYSTEM_PROMPT


def test_build_agent_options_attaches_no_in_process_server():
    # Rendering is no longer a tool, so CVI contributes no in-process MCP server. With
    # no external servers configured, the session runs with an empty server set.
    options = build_agent_options()
    assert options.mcp_servers == {}
    assert options.allowed_tools == []
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
    assert set(options.mcp_servers) == {"cfv", "claude-asset-renderer"}
    # Externals arrive as stdio specs; each server's tools are approved.
    assert options.mcp_servers["cfv"]["type"] == "stdio"
    assert "mcp__cfv" in options.allowed_tools
    assert "mcp__claude-asset-renderer" in options.allowed_tools
    # CVI fully owns its server set — no ambient CLI/project config is merged in.
    assert options.strict_mcp_config is True


_REMOTE_CONFIG = (
    "mcp_servers:\n"
    "  eddy:\n"
    "    command: npx\n"
    '    args: ["-y", "mcp-remote@0.1.38", "https://ex.internal/mcp"]\n'
    "    remote:\n"
    "      url: https://ex.internal/mcp\n"
    "      transport: http\n"
)


def test_build_agent_options_attaches_remote_server_with_bearer(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, _REMOTE_CONFIG)
    monkeypatch.setattr(mcp_server.remote_auth, "token_for", lambda name: "tok-123")
    options = build_agent_options()
    assert options.mcp_servers["eddy"] == {
        "type": "http",
        "url": "https://ex.internal/mcp",
        "headers": {"Authorization": "Bearer tok-123"},
    }
    assert "mcp__eddy" in options.allowed_tools


def test_build_agent_options_omits_remote_server_without_token(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, _REMOTE_CONFIG)
    monkeypatch.setattr(mcp_server.remote_auth, "token_for", lambda name: None)
    options = build_agent_options()
    # No keeper token yet → the server (and its tool allow) is left off this build.
    assert "eddy" not in options.mcp_servers
    assert "mcp__eddy" not in options.allowed_tools


def test_build_agent_options_passes_resume_session_id():
    assert build_agent_options(resume="sdk-xyz").resume == "sdk-xyz"
    assert build_agent_options().resume is None


def test_sessions_have_full_write_access():
    # No read-only gate: a headless chat runs with bypassPermissions (the CLI's
    # accept-all), so reads, edits, and commands are all permitted.
    options = build_agent_options()
    assert options.permission_mode == "bypassPermissions"
    assert options.can_use_tool is None
