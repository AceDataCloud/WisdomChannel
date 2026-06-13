"""`wisdom-channel bridge` — headless auto-reply loop (no Claude Code session).

The channels integration (``--dangerously-load-development-channels``) needs a
persistent interactive Claude Code session (a live TTY). For unattended /
no-TTY hosts, this loop provides the same "WeChat in → Claude answers → WeChat
out" behavior without one:

    Wisdom WS (inbound) → `claude -p` (headless, one-shot) → reply via Wisdom

It respects the same access allowlist as the channel (``access.json``) and the
same group @-mention gating.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess

import websockets
from loguru import logger

from wisdom_channel import client as api
from wisdom_channel.access import is_allowed, load_access
from wisdom_channel.config import WECHAT_BOT_NAME, WISDOM_WS_URL

SYSTEM_PROMPT = (
    "你是通过微信和用户对话的 AI 助手。用对方的语言、简洁口语化地回复,"
    "控制在 100 字内,不要使用 Markdown 标记。"
)
_RECONNECT_BASE_S = 2
_RECONNECT_MAX_S = 30
_CLAUDE_TIMEOUT_S = 120


def _is_at_me(text: str, mentions: list[str] | None) -> bool:
    if mentions:
        if WECHAT_BOT_NAME and WECHAT_BOT_NAME in mentions:
            return True
        if not WECHAT_BOT_NAME:
            return True
    if WECHAT_BOT_NAME:
        return f"@{WECHAT_BOT_NAME}" in text
    return "@" in text


def _strip_at_mention(text: str) -> str:
    if WECHAT_BOT_NAME:
        cleaned = text.replace(f"@{WECHAT_BOT_NAME}", "").strip()
        return cleaned or text
    cleaned = re.sub(r"@\S+\s*", "", text, count=1).strip()
    return cleaned or text


def _ask_claude(claude: str, text: str, model: str) -> str:
    try:
        proc = subprocess.run(
            [
                claude, "-p", text,
                "--tools", "",
                "--dangerously-skip-permissions",
                "--model", model,
                "--append-system-prompt", SYSTEM_PROMPT,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_CLAUDE_TIMEOUT_S,
        )
        return (proc.stdout or "").strip()
    except Exception as e:  # subprocess / timeout — log and skip this message
        logger.error("claude -p failed: {!r}", e)
        return ""


async def _handle(data: dict, claude: str, model: str) -> None:
    if data.get("direction") != "inbound":
        return
    if (data.get("msg_type") or data.get("type") or "text") != "text":
        return
    text = (data.get("text") or "").strip()
    if not text:
        return
    sender = data.get("sender_name") or data.get("sender") or ""
    if WECHAT_BOT_NAME and sender == WECHAT_BOT_NAME:
        return  # ignore our own messages
    conv_type = data.get("conversation_type") or "private"
    target = data.get("conversation_name") or data.get("target_name") or data.get("target") or sender
    if conv_type == "group":
        if not _is_at_me(text, data.get("mentions")):
            return
        text = _strip_at_mention(text)
    if not is_allowed(sender, load_access()):
        return

    logger.info("bridge inbound [{}] from={} -> {!r}", conv_type, sender, text)
    reply = await asyncio.to_thread(_ask_claude, claude, text, model)
    if not reply:
        logger.warning("bridge: empty reply for {!r}, skipping", text)
        return
    await api.send_message(target, reply)
    logger.info("bridge sent -> {}", target)


async def run_bridge(model: str = "sonnet") -> int:
    claude = shutil.which("claude")
    if not claude:
        logger.error("`claude` CLI not found on PATH — install Claude Code first.")
        return 1
    logger.info(
        "bridge starting: WS={} bot={!r} model={}",
        WISDOM_WS_URL.split("?")[0], WECHAT_BOT_NAME, model,
    )
    delay = _RECONNECT_BASE_S
    pending: set[asyncio.Task] = set()
    while True:
        try:
            async with websockets.connect(WISDOM_WS_URL, open_timeout=15, ping_interval=20) as ws:
                logger.info("bridge WS connected")
                delay = _RECONNECT_BASE_S
                async for raw in ws:
                    try:
                        ev = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if ev.get("event") == "message.new":
                        task = asyncio.create_task(_handle(ev.get("data") or {}, claude, model))
                        pending.add(task)
                        task.add_done_callback(pending.discard)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("bridge WS disconnected: {!r}; retry in {}s", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_S)
