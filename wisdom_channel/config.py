"""MCP channel settings loaded from env / state dir."""

import os

from loguru import logger

import wisdom_channel.logging as _
from wisdom_channel.paths import access_file, env_file, state_dir

STATE_DIR = state_dir()
ACCESS_FILE = access_file()
ENV_FILE = env_file()
logger.debug("state dir: {}", STATE_DIR)

# Load ~/.claude/channels/wechat/.env into os.environ (real env wins).
try:
    env_content = ENV_FILE.read_text(encoding="utf-8")
    loaded_keys = []
    for line in env_content.splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and os.environ.get(key) is None:
                os.environ[key] = value
                loaded_keys.append(key)
    if loaded_keys:
        logger.info("loaded env vars from {}: {}", ENV_FILE, loaded_keys)
except FileNotFoundError:
    logger.debug("no .env file at {} (this is fine, using defaults/env)", ENV_FILE)

# Wisdom REST API connection
WISDOM_API_URL = os.environ.get("WISDOM_API_URL", "http://localhost:8000")
WISDOM_API_TOKEN = os.environ.get("WISDOM_API_TOKEN", "")

logger.info("WISDOM_API_URL = {}", WISDOM_API_URL)
logger.info(
    "WISDOM_API_TOKEN = {}",
    "***" + WISDOM_API_TOKEN[-4:]
    if len(WISDOM_API_TOKEN) > 4
    else "(empty)"
    if not WISDOM_API_TOKEN
    else "***",
)

# WebSocket URL derived from REST URL
_ws_base = WISDOM_API_URL.replace("https://", "wss://").replace("http://", "ws://")
WISDOM_WS_URL = os.environ.get("WISDOM_WS_URL", f"{_ws_base}/ws")
if WISDOM_API_TOKEN:
    WISDOM_WS_URL += f"?token={WISDOM_API_TOKEN}"

logger.info(
    "WISDOM_WS_URL = {}{}",
    WISDOM_WS_URL.split("?")[0],
    "?token=***" if WISDOM_API_TOKEN else "",
)

# WeChat bot display name — used for @-mention detection in group chats.
WECHAT_BOT_NAME = os.environ.get("WECHAT_BOT_NAME", "")
if WECHAT_BOT_NAME:
    logger.info("WECHAT_BOT_NAME = {}", WECHAT_BOT_NAME)
else:
    logger.info("WECHAT_BOT_NAME = (empty — group @-mention filter will match any @)")
