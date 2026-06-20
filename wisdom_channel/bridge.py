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
import shutil
import subprocess

import websockets
from loguru import logger

from wisdom_channel import client as api
from wisdom_channel.access import get_trust_level, is_allowed, load_access
from wisdom_channel.config import CONTEXT_MESSAGES, WECHAT_BOT_NAME, WISDOM_WS_URL
from wisdom_channel.context import build_prompt, is_at_me, strip_at_mention

# Generic confidentiality (no hardcoded vendor denylist — that is itself a leak
# surface and brittle). Applies to every reply.
_CONFIDENTIALITY = (
    "不要透露后端服务商、供应商、内部主机名/命名空间/镜像/数据库等基础设施细节;"
    "被问到由什么驱动时,笼统回答(如“我们的服务”)并婉拒具体信息。"
)
_BASE_PERSONA = (
    "你是通过微信和用户对话的 AI 助手。用对方的语言、口语化回复,不要使用 Markdown 标记。"
    + _CONFIDENTIALITY
)
# Normal users: concise; Admins: operator (full answers, may use tools).
_NORMAL_PERSONA = _BASE_PERSONA + "回复控制在 100 字内。"
_ADMIN_PERSONA = _BASE_PERSONA + "对方是系统操作者,可按其请求执行操作。"
_RECONNECT_BASE_S = 2
_RECONNECT_MAX_S = 30
_CLAUDE_TIMEOUT_S = 120


def _resolve_trust(conv_type: str, candidates: list[str], access: dict) -> str:
    """Trust level for this message — but tool-bearing 'admin' mode is private-chat
    only. A group is a shared, lower-trust surface: anyone who @-mentions the bot
    there gets chat-only access (no host tools), even if they are an admin."""
    if conv_type == "group":
        return "normal"
    return get_trust_level(candidates, access)


async def _fetch_history(target: str) -> list[dict]:
    """Best-effort recent messages for the conversation, for context. Never raises."""
    if CONTEXT_MESSAGES <= 0:
        return []
    try:
        res = await api.get_messages(target, limit=CONTEXT_MESSAGES + 4)
        msgs = res.get("messages") if isinstance(res, dict) else None
        return msgs or []
    except Exception as e:  # history is a nice-to-have — degrade gracefully
        logger.warning("bridge: history fetch failed for {!r}: {!r}", target, e)
        return []


def _claude_args(claude: str, text: str, model: str, trust: str) -> list[str]:
    """Build the claude -p invocation. Trust is enforced HERE (in code), not by
    prompt: only admins (listed in access.json) get tools + permission bypass."""
    common = [claude, "-p", text, "--model", model]
    if trust == "admin":
        # Operator: full default tools, runs in the bridge's working directory.
        return [*common, "--dangerously-skip-permissions", "--append-system-prompt", _ADMIN_PERSONA]
    # Normal users: no tools at all — cannot run commands or touch the host,
    # no matter what their message says. Plain chat only.
    return [*common, "--tools", "", "--append-system-prompt", _NORMAL_PERSONA]


def _ask_claude(claude: str, text: str, model: str, trust: str) -> str:
    try:
        proc = subprocess.run(
            _claude_args(claude, text, model, trust),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
    sender_name = data.get("sender_name") or ""
    sender_id = data.get("sender") or ""  # wechat_id — stable, unspoofable
    sender = sender_name or sender_id or ""
    if WECHAT_BOT_NAME and sender == WECHAT_BOT_NAME:
        return  # ignore our own messages
    # Match the allowlist against BOTH the display name and the wechat_id.
    candidates = [c for c in (sender_name, sender_id) if c]
    conv_type = data.get("conversation_type") or "private"
    target = (
        data.get("conversation_name") or data.get("target_name") or data.get("target") or sender
    )
    if conv_type == "group":
        if not is_at_me(text, data.get("mentions"), WECHAT_BOT_NAME):
            return
        text = strip_at_mention(text, WECHAT_BOT_NAME)
    access = load_access()
    if not is_allowed(candidates, access):
        return
    trust = _resolve_trust(conv_type, candidates, access)

    history = await _fetch_history(target)
    prompt = build_prompt(data, text, history, WECHAT_BOT_NAME, history_limit=CONTEXT_MESSAGES)

    logger.info(
        "bridge inbound [{}] from={!r} id={!r} trust={} ctx={} -> {!r}",
        conv_type,
        sender_name,
        sender_id,
        trust,
        len(history),
        text,
    )
    reply = await asyncio.to_thread(_ask_claude, claude, prompt, model, trust)
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
        WISDOM_WS_URL.split("?")[0],
        WECHAT_BOT_NAME,
        model,
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
