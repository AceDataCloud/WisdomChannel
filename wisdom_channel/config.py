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

# How many recent messages to pull from Wisdom as conversation context for each
# reply (0 disables history injection). Keeps Claude aware of the running thread.
try:
    CONTEXT_MESSAGES = int(os.environ.get("WECHAT_CONTEXT_MESSAGES", "8"))
except ValueError:
    CONTEXT_MESSAGES = 8
logger.info("WECHAT_CONTEXT_MESSAGES = {}", CONTEXT_MESSAGES)

# WeChat bot display name — used for @-mention detection in group chats.
WECHAT_BOT_NAME = os.environ.get("WECHAT_BOT_NAME", "")
if WECHAT_BOT_NAME:
    logger.info("WECHAT_BOT_NAME = {}", WECHAT_BOT_NAME)
else:
    logger.info("WECHAT_BOT_NAME = (empty — group @-mention filter will match any @)")


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Output-side confidentiality scrub (defence-in-depth over the prompt guardrail).
# Every outbound reply is redacted of upstream provider aliases / internal infra
# identifiers before it reaches WeChat. Denylist lives in code + scrub.json, not
# in the model prompt. mode: "redact" (replace tokens) or "block" (drop the reply).
SCRUB_ENABLED = _env_bool("WECHAT_SCRUB_ENABLED", True)
SCRUB_MODE = os.environ.get("WECHAT_SCRUB_MODE", "redact").strip().lower()
SCRUB_REPLACEMENT = os.environ.get("WECHAT_SCRUB_REPLACEMENT", "我们的服务")
SCRUB_BLOCK_MESSAGE = os.environ.get(
    "WECHAT_SCRUB_BLOCK_MESSAGE", "抱歉，这个问题我暂时不方便回答。"
)
logger.info("WECHAT_SCRUB_ENABLED = {} (mode={})", SCRUB_ENABLED, SCRUB_MODE)
