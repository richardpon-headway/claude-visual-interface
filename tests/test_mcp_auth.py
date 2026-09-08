"""The shared remote-MCP auth keepers: token reading, keeper lifecycle (authenticate →
hand out token → shut down), npx preflight, and registry selection of remote servers.

The `mcp-remote` subprocess is faked at the `_create_subprocess` seam so the tests are
hermetic (no PATH / npx / network), mirroring the fake-SDK pattern in test_agent_session.
"""

import asyncio
import json
from pathlib import Path

import daemon.mcp_auth as mcp_auth
from daemon.mcp_auth import RemoteMcpAuthKeeper, RemoteMcpAuthRegistry


def _write_token(config_dir: Path, token: str, expires_in: int = 900) -> None:
    """Write a token file shaped like mcp-remote's into an isolated cache dir."""
    d = Path(config_dir) / "mcp-remote-0.1.37"
    d.mkdir(parents=True, exist_ok=True)
    (d / "abc123_tokens.json").write_text(
        json.dumps(
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "refresh_token": "r",
                "scope": "mcp",
            }
        )
    )


class _FakeProc:
    """Stand-in for asyncio's subprocess: alive until terminated."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def _keeper(tmp_path: Path) -> RemoteMcpAuthKeeper:
    return RemoteMcpAuthKeeper(
        "eddy", "npx", ["x"], None, "https://x/mcp", "http", auth_base=tmp_path
    )


def test_read_token_from_disk_returns_token_and_expiry(tmp_path):
    keeper = _keeper(tmp_path)
    assert keeper._read_token_from_disk() is None
    _write_token(tmp_path / "eddy", "tok-abc", expires_in=900)
    result = keeper._read_token_from_disk()
    assert result is not None
    token, expiry = result
    assert token == "tok-abc"
    assert expiry is not None and expiry > 0


def test_read_token_from_disk_ignores_malformed(tmp_path):
    keeper = _keeper(tmp_path)
    d = tmp_path / "eddy" / "mcp-remote-0.1.37"
    d.mkdir(parents=True)
    (d / "x_tokens.json").write_text("{not json")
    assert keeper._read_token_from_disk() is None


async def test_keeper_authenticates_then_shuts_down(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_auth, "_INITIAL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(mcp_auth, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(mcp_auth.shutil, "which", lambda cmd: "/usr/bin/" + cmd)
    keeper = _keeper(tmp_path)
    proc = _FakeProc()

    async def fake_spawn(command, args, env):
        # Simulate mcp-remote authenticating and writing its token into the isolated dir.
        _write_token(Path(env["MCP_REMOTE_CONFIG_DIR"]), "tok-live", expires_in=10_000)
        return proc

    monkeypatch.setattr(mcp_auth, "_create_subprocess", fake_spawn)

    keeper.start()
    for _ in range(200):
        if keeper.current_token() == "tok-live":
            break
        await asyncio.sleep(0.01)
    assert keeper.current_token() == "tok-live"

    await keeper.aclose()
    assert proc.terminated
    assert keeper.current_token() is None


async def test_keeper_without_npx_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_auth.shutil, "which", lambda cmd: None)
    keeper = _keeper(tmp_path)
    keeper.start()
    await asyncio.sleep(0.05)
    assert keeper.current_token() is None
    await keeper.aclose()


async def test_registry_starts_only_remote_keepers(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_auth, "_AUTH_BASE", tmp_path / "auth")
    monkeypatch.setattr(mcp_auth, "_INITIAL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(mcp_auth.shutil, "which", lambda cmd: "/usr/bin/" + cmd)

    async def fake_spawn(command, args, env):
        return _FakeProc()

    monkeypatch.setattr(mcp_auth, "_create_subprocess", fake_spawn)

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "mcp_servers:\n"
        "  cfv:\n"
        "    command: uv\n"
        '    args: ["run"]\n'
        "  eddy:\n"
        "    command: npx\n"
        '    args: ["mcp-remote", "https://ex/mcp"]\n'
        "    remote:\n"
        "      url: https://ex/mcp\n"
        "      transport: http\n"
    )
    monkeypatch.setenv("CVI_CONFIG_PATH", str(cfg))

    registry = RemoteMcpAuthRegistry()
    registry.startup_all()
    # Only the remote server gets a keeper; the local stdio server does not.
    assert registry.token_for("cfv") is None  # no keeper for a local stdio server
    assert "eddy" in registry._keepers
    assert "cfv" not in registry._keepers
    await registry.shutdown_all()
    assert registry._keepers == {}
