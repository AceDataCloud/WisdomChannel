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
from wisdom_channel.access import AccessDecision, load_access, resolve_access, trusted_sender_id
from wisdom_channel.config import CONTEXT_MESSAGES, WECHAT_BOT_NAME, WISDOM_WS_URL
from wisdom_channel.context import build_prompt, is_at_me, strip_at_mention

# Generic confidentiality (no hardcoded vendor denylist — that is itself a leak
# surface and brittle). Applies to every reply.
_CONFIDENTIALITY = (
    "不要透露后端服务商、供应商、上游接口、密钥/令牌、底层源码或实现细节、"
    "内部主机名/命名空间/镜像/数据库等基础设施细节;"
    "被问到由什么驱动时,笼统回答(如“我们的服务”)并婉拒具体信息。"
)
_BASE_PERSONA = (
    "你是通过微信和用户对话的 AI 助手。用对方的语言、口语化回复,不要使用 Markdown 标记。"
    + _CONFIDENTIALITY
)
_RECONNECT_BASE_S = 2
_RECONNECT_MAX_S = 30
_CLAUDE_TIMEOUT_S = 120
def _resolve_trust(conv_type: str, candidates: list[str], access: dict) -> str:
    """Backward-compatible helper for tests; real code uses resolve_access()."""
    sender_id = candidates[-1] if candidates else ""
    sender_name = candidates[0] if len(candidates) > 1 else ""
    decision = resolve_access(
        sender_name=sender_name,
        sender_id=sender_id,
        conversation_name="Ace Data Cloud客户群1" if conv_type == "group" else "",
        conversation_type=conv_type,
        access=access,
    )
    return decision.trust_level if decision.allowed else "normal"


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


def _claude_args(
    claude: str,
    text: str,
    model: str,
    role: str,
    allow_tools: bool,
    access_prompt: str = "",
) -> list[str]:
    """Build the claude -p invocation. Tool access is enforced in code."""
    common = [claude, "-p", text, "--model", model]
    role_line = f"当前微信访问角色: {role}。"
    persona = _BASE_PERSONA + "\n" + role_line + ("\n" + access_prompt if access_prompt else "")
    if allow_tools:
        return [*common, "--dangerously-skip-permissions", "--append-system-prompt", persona]
    return [*common, "--tools", "", "--append-system-prompt", persona]


def _ask_claude(claude: str, text: str, model: str, decision: AccessDecision) -> str:
    try:
        proc = subprocess.run(
            _claude_args(
                claude,
                text,
                model,
                decision.role,
                decision.allow_tools,
                decision.prompt,
            ),
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
    access = load_access()
    sender_name = data.get("sender_name") or ""
    sender_id = trusted_sender_id(data, access)
    sender = sender_name or sender_id or ""
    if WECHAT_BOT_NAME and sender == WECHAT_BOT_NAME:
        return  # ignore our own messages
    conv_type = data.get("conversation_type") or ""
    if conv_type not in {"group", "private"}:
        logger.info("bridge dropped message with unknown conversation_type={!r}", conv_type)
        return
    target = (
        data.get("conversation_name") or data.get("target_name") or data.get("target") or sender
    )
    if conv_type == "group":
        if not is_at_me(text, data.get("mentions"), WECHAT_BOT_NAME):
            return
        text = strip_at_mention(text, WECHAT_BOT_NAME)
    decision = resolve_access(
        sender_name=sender_name,
        sender_id=sender_id,
        conversation_name=target,
        conversation_type=conv_type,
        access=access,
    )
    if not decision.allowed:
        logger.info(
            "bridge dropped [{}] from={!r} id={!r}: {}",
            conv_type,
            sender_name,
            sender_id,
            decision.reason,
        )
        return

    history = await _fetch_history(target)
    prompt = build_prompt(data, text, history, WECHAT_BOT_NAME, history_limit=CONTEXT_MESSAGES)

    logger.info(
        "bridge inbound [{}] from={!r} id={!r} trust={} ctx={} -> {!r}",
        conv_type,
        sender_name,
        sender_id,
        decision.trust_level,
        len(history),
        text,
    )
    reply = await asyncio.to_thread(_ask_claude, claude, prompt, model, decision)
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
