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
