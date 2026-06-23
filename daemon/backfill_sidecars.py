"""One-shot backfill: write token-monitor sidecars for existing CVI sessions.

CVI only writes sidecars for sessions it touches going forward. This reclassifies
history by walking every session that already has an SDK session id and a real
(non-default) title and writing each one's sidecar, so claude-token-monitor splits
the historical catch-all bucket per conversation. Idempotent — safe to re-run.

Run via ``make backfill-sidecars``.
"""
from __future__ import annotations

from daemon import sessions
from daemon.session_sidecar import update_sidecar_for_session


def backfill() -> int:
    """Write a sidecar for every eligible existing session. Returns the count."""
    return sum(
        update_sidecar_for_session(session["id"])
        for session in sessions.list_sessions(include_archived=True)
    )


def main() -> None:
    count = backfill()
    print(f"wrote {count} token-monitor sidecar(s)")


if __name__ == "__main__":
    main()
