"""Single-owner auth for CVI's remote OAuth MCP servers (eddy, linear, glean).

Each such server is reached through `mcp-remote`, which runs an OAuth browser flow
whenever it can't reuse a cached token. CVI used to let every chat session spawn its own
`mcp-remote` per remote server — and respawn it across every idle→resume cycle — so many
instances raced to authenticate at once, opening a storm of browser tabs (worst right
after a daemon restart, when every open tab respawns its bridges together).

This module gives each remote server ONE long-lived, daemon-owned `mcp-remote` *auth
keeper*. The keeper performs the OAuth once (a single browser tab on cold start), holds
the connection open so its token stays refreshed, and exposes the current access token.
Chat sessions then attach to the remote server *directly* over HTTP/SSE with that token
injected as an `Authorization` header (see `build_agent_options`) — no per-session OAuth,
no storm. The ~18 per-session bridge processes collapse to one keeper per remote server.

Two deliberate implementation choices:

- **Isolated token cache.** Each keeper runs with its own `MCP_REMOTE_CONFIG_DIR`, so its
  token file is the only one in that directory. The daemon reads the token by globbing
  that directory rather than recomputing `mcp-remote`'s cache-file name — that name is an
  md5 of `url|resource|headers` and is brittle across `mcp-remote` versions.
- **Token freshness by polling + expiry-triggered restart.** The keeper re-reads its
  token file periodically (picking up a refresh `mcp-remote` wrote in place) and, if the
  on-disk token reaches expiry without being refreshed, cycles the process to force a
  fresh one. Access-token lifetimes vary widely (eddy ~15 min, glean ~24 h, linear
  ~7 days), so the margins below are module constants meant to be tuned against observed
  behavior. A session that snapshots a token in the narrow window around expiry can see a
  one-off auth failure; it self-heals on the next session respawn, which re-reads the
  current token.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import shutil
import time
from pathlib import Path

from daemon import config

log = logging.getLogger(__name__)

# One isolated mcp-remote token cache per server lives under here (a subdir per server),
# so the daemon reads a single token file by glob rather than recomputing mcp-remote's
# md5-based cache-file name. Persistent across daemon restarts so a restart reuses a
# still-valid token (and refresh token) instead of re-authenticating.
_AUTH_BASE = Path.home() / ".mcp-auth-cvi"

# Poll cadence for picking up a token mcp-remote wrote (initial auth vs steady state).
_INITIAL_POLL_SECONDS = 1.0
_POLL_INTERVAL_SECONDS = 20.0
# Cycle the keeper to force a fresh token once the on-disk token is within this many
# seconds of expiry and mcp-remote hasn't refreshed it in place. Tune against real token
# lifetimes (eddy's access token is ~15 min; glean ~24 h; linear ~7 days).
_REFRESH_LEAD_SECONDS = 60.0
# Bounded backoff between restarts after a crash, so a persistently-failing keeper (a
# revoked refresh token, the remote being down) doesn't hot-loop.
_BACKOFF_START_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0


async def _create_subprocess(
    command: str, args: list[str], env: dict[str, str]
) -> asyncio.subprocess.Process:
    """Spawn the keeper. `stdin` is an open pipe we never write to: mcp-remote treats a
    closed stdin as the MCP client disconnecting and exits, so an open-but-idle pipe
    keeps it alive holding the remote connection. stderr inherits the daemon's so
    mcp-remote's auth prompts/errors surface in the daemon terminal. A module-level seam
    so tests can substitute a fake process."""
    return await asyncio.create_subprocess_exec(
        command,
        *args,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
    )


class RemoteMcpAuthKeeper:
    """One long-lived `mcp-remote` per remote OAuth server: owns the single OAuth flow,
    keeps the token fresh, and hands out the current access token. Supervised — restarts
    on crash (bounded backoff) and cycles to force a refresh near token expiry."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
        url: str,
        transport: str,
        auth_base: Path | None = None,
    ) -> None:
        self._name = name
        self._command = command
        self._args = list(args)
        self._extra_env = dict(env or {})
        self._url = url
        self._transport = transport
        self._auth_dir = (auth_base or _AUTH_BASE) / name
        self._token: str | None = None
        self._token_expiry: float | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def url(self) -> str:
        return self._url

    @property
    def transport(self) -> str:
        return self._transport

    def current_token(self) -> str | None:
        """The freshest access token, or None until the keeper has authenticated."""
        return self._token

    def start(self) -> None:
        """Launch the supervised keeper loop (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        """Cancel the loop and tear the subprocess down cleanly."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self._extra_env)
        env["MCP_REMOTE_CONFIG_DIR"] = str(self._auth_dir)
        return env

    def _read_token_from_disk(self) -> tuple[str, float | None] | None:
        """Read the sole `*_tokens.json` in this keeper's isolated cache dir. Returns
        (access_token, expiry_epoch) — expiry is the file's mtime plus its `expires_in`,
        or None when the file omits a usable duration. None when no readable token yet."""
        pattern = str(self._auth_dir / "mcp-remote-*" / "*_tokens.json")
        files = glob.glob(pattern)
        if not files:
            return None
        newest = max(files, key=os.path.getmtime)
        try:
            with open(newest) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        expires_in = data.get("expires_in")
        expiry = (
            os.path.getmtime(newest) + float(expires_in)
            if isinstance(expires_in, (int, float))
            else None
        )
        return token, expiry

    async def _await_token(self, proc: asyncio.subprocess.Process) -> bool:
        """Wait for the keeper to write a token. No hard timeout — cold-start OAuth can
        take as long as the user needs at the browser — but give up if the process dies
        first. Returns True once a token is available."""
        while True:
            if proc.returncode is not None:
                return False
            tok = self._read_token_from_disk()
            if tok is not None:
                self._token, self._token_expiry = tok
                return True
            await asyncio.sleep(_INITIAL_POLL_SECONDS)

    async def _supervise(self, proc: asyncio.subprocess.Process) -> None:
        """Hold while the keeper runs: keep the in-memory token synced from disk, return
        (to restart) if the process exits or the token reaches expiry unrefreshed."""
        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            if proc.returncode is not None:
                log.warning("MCP auth keeper exited; restarting", extra={"server": self._name})
                return
            tok = self._read_token_from_disk()
            if tok is not None:
                self._token, self._token_expiry = tok
            if (
                self._token_expiry is not None
                and self._token_expiry - time.time() < _REFRESH_LEAD_SECONDS
            ):
                log.info(
                    "MCP auth keeper cycling to refresh token", extra={"server": self._name}
                )
                return

    async def _terminate(self, proc: asyncio.subprocess.Process | None) -> None:
        # SIGTERM is sent before the (cancellable) wait, so even if this coroutine is
        # cancelled while awaiting exit the process has already been signalled. Never
        # swallow a CancelledError here — let it propagate — and only escalate to kill on
        # a genuine wait timeout.
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def _run(self) -> None:
        if shutil.which(self._command) is None:
            # Fail loudly, not silently: the server simply won't get a token and is
            # omitted from sessions, but the reason is visible.
            log.error(
                "MCP auth keeper for %r cannot start: %r not found on PATH",
                self._name,
                self._command,
                extra={"server": self._name},
            )
            return
        backoff = _BACKOFF_START_SECONDS
        while True:
            proc: asyncio.subprocess.Process | None = None
            try:
                log.info("MCP auth keeper starting", extra={"server": self._name})
                self._auth_dir.mkdir(parents=True, exist_ok=True)
                proc = await _create_subprocess(self._command, self._args, self._build_env())
                if await self._await_token(proc):
                    backoff = _BACKOFF_START_SECONDS
                    log.info("MCP auth keeper authenticated", extra={"server": self._name})
                    await self._supervise(proc)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A background task with no instrumented boundary: log the swallow so the
                # crash is observable, then restart. (CancelledError is re-raised above;
                # the finally below tears the subprocess down on every exit path.)
                log.warning(
                    "MCP auth keeper crashed", extra={"server": self._name}, exc_info=True
                )
            finally:
                self._token = None
                self._token_expiry = None
                await self._terminate(proc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)


class RemoteMcpAuthRegistry:
    """The daemon-wide set of auth keepers, keyed by server name. In-memory,
    single-process (mirrors the `agents` session registry)."""

    def __init__(self) -> None:
        self._keepers: dict[str, RemoteMcpAuthKeeper] = {}

    def startup_all(self) -> None:
        """Start one keeper per configured remote-OAuth server. Non-blocking: keepers
        authenticate in the background so a slow browser click never blocks startup."""
        for name, spec in config.get_mcp_servers().items():
            if spec.get("type") != "remote":
                continue
            keeper = RemoteMcpAuthKeeper(
                name=name,
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env"),
                url=spec["url"],
                transport=spec["transport"],
            )
            self._keepers[name] = keeper
            keeper.start()
        if self._keepers:
            log.info(
                "started %d MCP auth keeper(s): %s",
                len(self._keepers),
                ", ".join(sorted(self._keepers)),
            )

    async def shutdown_all(self) -> None:
        for keeper in list(self._keepers.values()):
            await keeper.aclose()
        self._keepers.clear()

    def token_for(self, name: str) -> str | None:
        """The current access token for a remote server, or None when its keeper hasn't
        authenticated yet (the server is then omitted from a session build)."""
        keeper = self._keepers.get(name)
        return keeper.current_token() if keeper is not None else None


# The daemon owns a single registry for the whole process (mirrors `agents`).
remote_auth = RemoteMcpAuthRegistry()
