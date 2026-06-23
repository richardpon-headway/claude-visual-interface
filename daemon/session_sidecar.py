"""Write the token-monitor sidecar so claude-token-monitor (CTM) attributes a
CVI chat's tokens to its title instead of one catch-all bucket.

CTM reads ``~/.cache/claude-token-monitor/session-meta/<sdk-session-id>.json`` and,
when it carries a free-text ``topic``, relabels that session's usage by it. The SDK
session id is the JSONL filename CTM keys on; CVI stores it as
``session.agent_session_id``. The atomic write mirrors claude-developer-hub's
sidecar writer (tempfile + ``os.replace``) so a half-written file never appears at
the canonical path.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from daemon import sessions

log = logging.getLogger(__name__)

SIDECAR_DIR = Path.home() / ".cache" / "claude-token-monitor" / "session-meta"


def get_sidecar_dir() -> Path:
    """Resolve the sidecar dir, honoring ``CVI_TOKEN_MONITOR_SIDECAR_DIR`` (read at
    call time, so tests can redirect it)."""
    override = os.environ.get("CVI_TOKEN_MONITOR_SIDECAR_DIR")
    return Path(override).expanduser() if override else SIDECAR_DIR


def write_session_sidecar(sdk_session_id: str, topic: str) -> None:
    """Atomically write the token-monitor sidecar for one SDK session.

    Best-effort telemetry: a failure here must never break a chat turn or the
    backfill, so an ``OSError`` is logged (with the sdk session id) and swallowed —
    no instrumented boundary would otherwise see it.
    """
    payload = {
        "session_id": sdk_session_id,
        "topic": topic,
        "started_via": "cvi",
    }
    try:
        sidecar_dir = get_sidecar_dir()
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        final = sidecar_dir / f"{sdk_session_id}.json"
        fd, tmp = tempfile.mkstemp(
            prefix=f".{final.name}.", suffix=".tmp", dir=str(sidecar_dir)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, final)
        except OSError:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
    except OSError as e:
        log.warning(
            "failed to write token-monitor sidecar for sdk session %s: %s",
            sdk_session_id,
            e,
        )


def update_sidecar_for_session(surface: str) -> bool:
    """(Re)write the sidecar for a CVI surface from its current DB state.

    A no-op until the session has both an SDK session id (the file CTM keys on) and a
    real title — the two are set at different times, so every hook that can supply
    one re-drives this. The placeholder "New chat" title is skipped so a not-yet-
    titled session isn't attributed to the default bucket. Returns True iff a sidecar
    was written.
    """
    session = sessions.get_session(surface)
    if not session:
        return False
    sdk_session_id = session.get("agent_session_id")
    topic = sessions.effective_title(session)
    if not sdk_session_id or not topic or topic == sessions.DEFAULT_CHAT_TITLE:
        return False
    write_session_sidecar(sdk_session_id, topic)
    return True
