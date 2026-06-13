"""Single source of truth for the channel state directory and file paths.

Honors the ``WECHAT_STATE_DIR`` override everywhere (previously each module
re-derived the path, and ``logging.py`` ignored the override). Leaf module —
imports nothing from the package, so it is safe to import from anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT = Path.home() / ".claude" / "channels" / "wechat"


def state_dir() -> Path:
    """Return the channel state directory, creating it if needed."""
    d = Path(os.environ.get("WECHAT_STATE_DIR") or _DEFAULT)
    d.mkdir(parents=True, exist_ok=True)
    return d


def env_file() -> Path:
    return state_dir() / ".env"


def access_file() -> Path:
    return state_dir() / "access.json"


def log_file() -> Path:
    return state_dir() / "mcp.log"
