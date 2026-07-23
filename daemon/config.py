"""User-editable settings for the CVI daemon, backed by a small YAML file.

The file lives in the repo root (``config.yaml``) and is created with documented
defaults on first run. It is gitignored — it holds a machine-specific absolute path.
Settings are read at call time (like ``CVI_DB_PATH`` in ``db.py``) so an edit takes
effect on the next session without restarting the daemon. A missing file or an
unreadable/invalid value never crashes startup — it falls back to the built-in
default, logged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# .../claude-visual-interface/daemon/config.py -> .../claude-visual-interface (repo
# root) -> ... (the parent that holds sibling repos).
REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_PARENT = REPO_ROOT.parent

CONFIG_PATH = REPO_ROOT / "config.yaml"

_DEFAULT_CONFIG_TEMPLATE = """\
# CVI daemon settings.
#
# working_dir: directory every chat session is rooted at (the SDK cwd). Claude can
#   read and edit files under this path. Defaults to the parent of the CVI repo so
#   sibling repositories are visible. Use an absolute path; a leading ~ is expanded.
working_dir: {working_dir}
#
# mcp_servers: external stdio MCP servers attached to every chat session, alongside
#   the built-in `cvi` server. Each entry is name -> {{command, args, env?}} — the same
#   shape as ~/.claude.json mcpServers. The named server's own daemon must be running
#   for its tools to work. Uncomment and adjust paths to enable:
#
# mcp_servers:
#   cfv:
#     command: uv
#     args: ["run", "--directory", "/path/to/cfv", "python", "-m", "daemon.mcp_server"]
"""


def get_config_path() -> Path:
    """Resolve the config file path, honoring ``CVI_CONFIG_PATH`` (read at call time)."""
    override = os.environ.get("CVI_CONFIG_PATH")
    return Path(override).expanduser() if override else CONFIG_PATH


def _load() -> dict:
    """Parse the YAML config into a mapping. Absent file -> empty (use defaults);
    unreadable or non-mapping content -> empty + a warning, never an exception."""
    path = get_config_path()
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError):
        log.warning("could not read CVI config at %s; using defaults", path, exc_info=True)
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        log.warning("CVI config at %s is not a mapping; using defaults", path)
        return {}
    return data


def get_working_dir() -> Path:
    """The directory chat sessions run in. Falls back to the repo parent when the
    setting is missing, blank, or points at a non-directory (logged, not fatal)."""
    raw = _load().get("working_dir")
    if not raw:
        return REPO_PARENT
    candidate = Path(str(raw)).expanduser()
    if not candidate.is_dir():
        log.warning(
            "configured working_dir %s is not a directory; using %s", candidate, REPO_PARENT
        )
        return REPO_PARENT
    return candidate


def get_mcp_servers() -> dict[str, dict]:
    """External stdio MCP servers to attach to every chat session, read from the
    config's ``mcp_servers`` mapping (name -> {command, args, env}) and returned as SDK
    stdio-server specs. A malformed entry is skipped with a warning naming the key; a
    missing / blank / non-mapping section yields no servers. Never raises — one bad
    entry must not sink startup."""
    raw = _load().get("mcp_servers")
    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("config mcp_servers is not a mapping; ignoring")
        return {}
    servers: dict[str, dict] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            log.warning("skipping mcp_servers entry %r: not a mapping", name)
            continue
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            log.warning("skipping mcp_servers entry %r: missing or blank command", name)
            continue
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            log.warning("skipping mcp_servers entry %r: args must be a list of strings", name)
            continue
        entry: dict = {"type": "stdio", "command": command, "args": list(args)}
        env = spec.get("env")
        if env is not None:
            if not isinstance(env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            ):
                log.warning("skipping mcp_servers entry %r: env must be a string map", name)
                continue
            entry["env"] = dict(env)
        servers[str(name)] = entry
    return servers


def ensure_config_file() -> None:
    """Create the config file with documented defaults if it doesn't exist yet, so
    users have a discoverable, editable starting point. Never overwrites an existing
    file; a write failure is logged, not fatal."""
    path = get_config_path()
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE.format(working_dir=REPO_PARENT))
        log.info("wrote default CVI config to %s", path)
    except OSError:
        log.warning("could not write default CVI config to %s", path, exc_info=True)
