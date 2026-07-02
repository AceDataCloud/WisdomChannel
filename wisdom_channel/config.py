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


# --- Customer onboarding (scenario ④) ----------------------------------------
# When a new customer is added, auto-create a dedicated support group, name it,
# pull in the support team, and (optionally) add the customer to a shared big
# group + post a welcome message. Fully config-driven; nothing is hardcoded.


def _split_list(raw: str) -> list[str]:
    """Parse a comma/semicolon/newline-separated list into clean names."""
    parts: list[str] = []
    for chunk in raw.replace("；", ";").replace("，", ",").replace("\n", ",").split(","):
        for piece in chunk.split(";"):
            name = piece.strip()
            if name:
                parts.append(name)
    return parts


ONBOARDING_ENABLED = os.environ.get("ONBOARDING_ENABLED", "").lower() in ("1", "true", "yes", "on")
# Support-team members always pulled into the new group (nickname / remark / 微信号).
ONBOARDING_SUPPORT_MEMBERS = _split_list(os.environ.get("ONBOARDING_SUPPORT_MEMBERS", ""))
# Name template; ``{customer}`` is substituted with the customer's display name.
ONBOARDING_GROUP_NAME_TEMPLATE = os.environ.get(
    "ONBOARDING_GROUP_NAME_TEMPLATE", "{customer}专属客服群"
)
# Optional existing "big" customer group to also invite the new customer into.
ONBOARDING_BIG_GROUP = os.environ.get("ONBOARDING_BIG_GROUP", "").strip()
# Optional welcome message posted into the new support group.
ONBOARDING_WELCOME = os.environ.get("ONBOARDING_WELCOME", "").strip()

logger.info(
    "ONBOARDING enabled={} support={} template={!r} big_group={!r} welcome={}",
    ONBOARDING_ENABLED,
    ONBOARDING_SUPPORT_MEMBERS,
    ONBOARDING_GROUP_NAME_TEMPLATE,
    ONBOARDING_BIG_GROUP or "(none)",
    "set" if ONBOARDING_WELCOME else "(none)",
)
