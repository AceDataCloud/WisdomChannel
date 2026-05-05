"""Centralized loguru logging for the WeChat MCP channel.

Logs to both stderr (for MCP debug) and a file at
~/.claude/channels/wechat/mcp.log (for post-hoc inspection).

stdout is NEVER used — it's reserved for MCP JSON-RPC.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

# Remove default loguru handler (which writes to stderr with colors)
logger.remove()

# State dir — same as config.py uses
_state_dir = Path.home() / ".claude" / "channels" / "wechat"
_state_dir.mkdir(parents=True, exist_ok=True)
LOG_FILE = _state_dir / "mcp.log"

# File handler — main log destination, rotation at 5 MB
logger.add(
    LOG_FILE,
    format="{time:HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}",
    level="DEBUG",
    rotation="5 MB",
    retention="3 days",
    encoding="utf-8",
    enqueue=True,  # thread-safe
)

# Stderr handler — for live debug when MCP server runs under Claude Code
logger.add(
    sys.stderr,
    format="[wechat-mcp] {time:HH:mm:ss.SSS} | {level:<7} | {message}",
    level="DEBUG",
    colorize=False,
)

logger.info("loguru configured: file={}, stderr=on", LOG_FILE)
