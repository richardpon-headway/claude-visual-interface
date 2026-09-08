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
- **Token freshness by polling, with an expiry-triggered restart as the fallback.** The
  keeper re-reads its token file periodically and serves whatever is currently valid. If
  `mcp-remote` refreshes the token in place (holding its connection open), polling picks
  the new one up with no restart at all. If instead the on-disk token actually reaches
  expiry without being refreshed, the keeper restarts the process — which forces a refresh
  via the cached refresh token — as a fallback. Crucially it keeps serving the last
  still-valid token across that restart (it is only withheld once genuinely expired), so a
  routine refresh doesn't blank a token that still works. Access-token lifetimes vary
  widely (eddy ~15 min, glean ~24 h, linear ~7 days); a session that snapshots a token can
  still see a one-off failure in the brief window at actual expiry, which self-heals on the
  next session respawn.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import shutil
import signal
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
# Floor on the steady-state poll delay when a token is approaching expiry — the supervise
# loop wakes near expiry (so a short-lived token like eddy's ~15 min is caught promptly)
# but never busy-spins.
_MIN_POLL_SECONDS = 1.0
# Bounded backoff between restarts after a crash, so a persistently-failing keeper (a
# revoked refresh token, the remote being down) doesn't hot-loop.
_BACKOFF_START_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0
# How long to wait for a signalled keeper to exit before escalating from SIGTERM to SIGKILL.
_TERMINATE_TIMEOUT_SECONDS = 5.0


def _kill_process_group(pid: int, sig: int) -> None:
    """Signal the whole process group led by `pid`. The keeper is spawned with
    start_new_session, so it leads its own group and its `mcp-remote` grandchild shares it
    — signalling the group reaps the grandchild too, which a bare per-process signal would
    orphan. A module-level seam so tests can observe the signal without real processes."""
    os.killpg(os.getpgid(pid), sig)


async def _create_subprocess(
    command: str, args: list[str], env: dict[str, str]
) -> asyncio.subprocess.Process:
    """Spawn the keeper. `stdin` is an open pipe we never write to: mcp-remote treats a
    closed stdin as the MCP client disconnecting and exits, so an open-but-idle pipe
    keeps it alive holding the remote connection. stderr inherits the daemon's so
    mcp-remote's auth prompts/errors surface in the daemon terminal. `start_new_session`
    puts the keeper in its own process group so teardown can reap the whole tree (npx +
    its node grandchild). A module-level seam so tests can substitute a fake process."""
    return await asyncio.create_subprocess_exec(
        command,
        *args,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


def _restrict_dir_perms(path: Path) -> None:
    """Best-effort owner-only (0700) perms on the token-cache dirs — they hold OAuth
    refresh tokens. The token FILES are already 0600 (written by mcp-remote); this
    tightens the enclosing directories too."""
    for p in (path, path.parent):
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass


class RemoteMcpAuthKeeper:
    """One long-lived `mcp-remote` per remote OAuth server: owns the single OAuth flow,
    keeps the token fresh, and hands out the current access token. Supervised — restarts
    on crash (bounded backoff); restarts at actual token expiry to force a refresh, as a
    fallback for when the bridge doesn't refresh in place."""

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
        """The freshest still-valid access token, or None if we have none or the last one
        we read has passed its expiry. Held across a process restart so a routine refresh
        cycle never blanks a token that's still good."""
        if self._token is None:
            return None
        if self._token_expiry is not None and self._token_expiry <= time.time():
            return None
        return self._token

    def start(self) -> None:
        """Launch the supervised keeper loop (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        """Cancel the loop, tear the subprocess down cleanly, and drop the token. Unlike a
        routine refresh restart (which keeps serving the still-valid token), an explicit
        close is the end of this keeper's life, so the token is cleared here."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._token = None
        self._token_expiry = None

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
            log.debug("MCP auth keeper token file unreadable", extra={"server": self._name})
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

    async def _supervise(self, proc: asyncio.subprocess.Process) -> str:
        """Hold while the keeper runs; keep the in-memory token synced from disk so an
        in-place refresh is picked up with no restart at all. Wakes near expiry so a
        short-lived token is caught promptly. Returns the restart reason: 'exited' (the
        process died — a crash) or 'refresh' (the token has actually expired and no newer
        one appeared, so relaunching forces a refresh via the cached refresh token)."""
        while True:
            remaining = (
                self._token_expiry - time.time() if self._token_expiry is not None else None
            )
            delay = (
                _POLL_INTERVAL_SECONDS
                if remaining is None
                else min(_POLL_INTERVAL_SECONDS, max(_MIN_POLL_SECONDS, remaining))
            )
            await asyncio.sleep(delay)
            if proc.returncode is not None:
                log.warning("MCP auth keeper exited; restarting", extra={"server": self._name})
                return "exited"
            tok = self._read_token_from_disk()
            if tok is not None:
                self._token, self._token_expiry = tok
            # Only cycle once the token has ACTUALLY expired: mcp-remote reuses a token
            # that still works, so restarting earlier would thrash without refreshing.
            if self._token_expiry is not None and self._token_expiry <= time.time():
                log.info(
                    "MCP auth keeper token expired; restarting to refresh",
                    extra={"server": self._name},
                )
                return "refresh"

    async def _terminate(self, proc: asyncio.subprocess.Process | None) -> None:
        # Signal the whole process group, not just the direct child: the keeper is
        # `npx mcp-remote`, whose real worker (node) is a grandchild, so a bare signal
        # would orphan the node bridge. SIGTERM is sent before the (cancellable) wait, so
        # even if this coroutine is cancelled while awaiting exit the group has already
        # been signalled. Never swallow a CancelledError here — let it propagate — and
        # only escalate to kill on a genuine wait timeout.
        if proc is None or proc.returncode is not None:
            return
        try:
            _kill_process_group(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_TIMEOUT_SECONDS)
        except TimeoutError:
            try:
                _kill_process_group(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    async def _run(self) -> None:
        if shutil.which(self._command) is None:
            # Fail loudly, not silently: the server simply won't get a token and is
            # omitted from sessions, but the reason is visible.
            log.error(
                "MCP auth keeper cannot start: command %r not found on PATH",
                self._command,
                extra={"server": self._name},
            )
            return
        backoff = _BACKOFF_START_SECONDS
        while True:
            proc: asyncio.subprocess.Process | None = None
            reason = "exited"
            try:
                log.info("MCP auth keeper starting", extra={"server": self._name})
                self._auth_dir.mkdir(parents=True, exist_ok=True)
                _restrict_dir_perms(self._auth_dir)
                proc = await _create_subprocess(self._command, self._args, self._build_env())
                if await self._await_token(proc):
                    backoff = _BACKOFF_START_SECONDS
                    log.info("MCP auth keeper authenticated", extra={"server": self._name})
                    reason = await self._supervise(proc)
                else:
                    log.warning(
                        "MCP auth keeper exited before authenticating; restarting",
                        extra={"server": self._name},
                    )
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
                await self._terminate(proc)
            # A planned refresh restart is immediate — we want the new token fast; only a
            # crash/exit backs off (so a routine refresh can't drift the delay toward the
            # cap, and a dead upstream still backs off). The token is not blanked here:
            # current_token() stops serving it once it actually expires, so it keeps being
            # served (while valid) right through the restart.
            if reason == "refresh":
                continue
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
