"""SQLite schema management for the CVI daemon.

A tiny hand-rolled migration runner (no Alembic). Numbered ``NNN_name.sql``
files in ``migrations/`` are applied in lexical order, exactly once each; a
``_migration`` table records what has been applied, so re-running is a no-op.

Migrations are copy-preserving by default: a schema-changing migration must
carry existing user rows forward (``INSERT ... SELECT``) rather than dropping
them. Sessions hold user input that must never be thrown away — the daemon
also snapshots the DB file before applying pending migrations.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path.home() / "Library" / "Application Support" / "cvi" / "cvi.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_MIGRATION_FILE_RE = re.compile(r"^\d{3,}_[A-Za-z0-9_]+\.sql$")

MAX_BACKUPS = 7
BACKUP_STALE_AFTER_SECONDS = 24 * 60 * 60

# foreign_keys and busy_timeout are session-scoped, so they are re-applied on
# every connection; journal_mode and synchronous persist in the file once set.
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)


def get_db_path() -> Path:
    """Resolve the DB path, honoring ``CVI_DB_PATH`` (read at call time)."""
    override = os.environ.get("CVI_DB_PATH")
    return Path(override).expanduser() if override else DB_PATH


def open_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path())
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _discover_migrations() -> list[Path]:
    files = [p for p in MIGRATIONS_DIR.glob("*.sql") if _MIGRATION_FILE_RE.match(p.name)]
    return sorted(files, key=lambda p: p.name)


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migration (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM _migration").fetchall()
    return {row[0] for row in rows}


def _backup_if_stale(db_path: Path) -> None:
    """Snapshot the DB file before migrating, at most once per 24h.

    Keeps the newest ``MAX_BACKUPS`` snapshots. Skipped when there is no DB
    file yet (a fresh install has nothing to preserve).
    """
    if not db_path.exists():
        return

    backups = sorted(db_path.parent.glob(f"{db_path.name}.bak.*"))
    if backups:
        newest = backups[-1].stat().st_mtime
        age = datetime.now(UTC).timestamp() - newest
        if age < BACKUP_STALE_AFTER_SECONDS:
            return

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    shutil.copy2(db_path, db_path.parent / f"{db_path.name}.bak.{stamp}")

    backups = sorted(db_path.parent.glob(f"{db_path.name}.bak.*"))
    for stale in backups[:-MAX_BACKUPS]:
        stale.unlink()


def _apply_one(conn: sqlite3.Connection, migration: Path) -> None:
    # executescript implicitly commits any open transaction first, so the
    # runner can't wrap a script from outside; each migration owns its own
    # BEGIN/COMMIT. On error, roll back the partial script and re-raise.
    sql = migration.read_text()
    try:
        conn.executescript(sql)
    except sqlite3.Error:
        conn.rollback()
        raise
    conn.execute(
        "INSERT INTO _migration (name, applied_at) VALUES (?, ?)",
        (migration.name, _now_iso()),
    )
    conn.commit()


def apply_migrations_sync(db_path: Path | None = None) -> None:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_if_stale(path)

    conn = open_db(path)
    try:
        _ensure_migration_table(conn)
        applied = _applied_migrations(conn)
        pending = [m for m in _discover_migrations() if m.name not in applied]
        for migration in pending:
            log.info("applying migration %s", migration.name)
            _apply_one(conn, migration)
        if pending:
            log.info("applied %d migration(s)", len(pending))
        else:
            log.info("schema up to date")
    finally:
        conn.close()


async def apply_migrations(db_path: Path | None = None) -> None:
    await asyncio.to_thread(apply_migrations_sync, db_path)
