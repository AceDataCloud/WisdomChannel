"""Pure helpers that turn a WeChat message + recent history into a context-rich
prompt for Claude.

Kept free of I/O and module-level config so it is trivially unit-testable: the
bot's own display name is always passed in explicitly.

What the bridge used to send Claude was just the raw message text. These helpers
add the surrounding context a human would have: who is speaking, which group,
who else was @-mentioned, the quoted ("引用") message, and the last few turns of
the conversation — so replies are coherent instead of context-free.
"""

from __future__ import annotations

import re

# WeChat renders a group @-mention as ``@<name>`` followed by U+2005 (FOUR-PER-EM
# SPACE), not an ordinary space. The old ``@(\S+)`` parsing broke on names with
# spaces and never matched this separator. Handle both.
_AT_SEP = " "

_NON_TEXT_PLACEHOLDER = {
    "image": "[图片]",
    "video": "[视频]",
    "file": "[文件]",
    "voice": "[语音]",
    "link": "[链接]",
    "sticker": "[表情]",
    "location": "[位置]",
    "system": "[系统消息]",
}


def is_at_me(text: str, mentions: list[str] | None, bot_name: str) -> bool:
    """Whether a group message @-mentions the bot.

    Prefers the structured ``mentions`` list; falls back to scanning the text for
    ``@<bot_name>`` (with the WeChat U+2005 separator, a trailing space, or at
    end-of-string). When ``bot_name`` is unknown, any mention/``@`` counts.
    """
    if mentions:
        if bot_name:
            if bot_name in mentions:
                return True
        else:
            return True
    if bot_name:
        marker = f"@{bot_name}"
        return (
            f"{marker}{_AT_SEP}" in text or f"{marker} " in text or text.rstrip().endswith(marker)
        )
    return "@" in text


def strip_at_mention(text: str, bot_name: str) -> str:
    """Remove the ``@<bot>`` token(s) so Claude sees just the user's words."""
    if bot_name:
        cleaned = text
        for token in (f"@{bot_name}{_AT_SEP}", f"@{bot_name} ", f"@{bot_name}"):
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.strip()
    else:
        # Drop one leading @segment: name runs until the U+2005 sep or whitespace.
        cleaned = re.sub(rf"@[^{_AT_SEP}\s]+[{_AT_SEP}\s]?", "", text, count=1).strip()
    return cleaned or text


def other_mentions(mentions: list[str] | None, bot_name: str) -> list[str]:
    """Mentions in the message other than the bot itself (deduped, order kept)."""
    out: list[str] = []
    for m in mentions or []:
        if m and m != bot_name and m not in out:
            out.append(m)
    return out


def _speaker(msg: dict, bot_name: str) -> str:
    who = msg.get("sender_name") or msg.get("sender") or "?"
    if msg.get("direction") == "outbound" or (bot_name and who == bot_name):
        return "你(机器人)"
    return str(who)


def _body(msg: dict) -> str:
    text = (msg.get("text") or "").strip()
    if text:
        return text
    return _NON_TEXT_PLACEHOLDER.get((msg.get("type") or "").lower(), "[消息]")


def format_history(
    messages: list[dict] | None,
    bot_name: str,
    *,
    current_text: str = "",
    limit: int = 8,
) -> str:
    """Render recent messages oldest→newest as ``发言人：内容`` lines.

    ``messages`` is what ``GET /api/messages?order=desc`` returns (newest first);
    we reverse to chronological. The newest entry is dropped when it duplicates
    the message currently being answered (``current_text``), so it isn't shown
    twice.
    """
    msgs = list(reversed(messages or []))
    cur = (current_text or "").strip()
    if cur and msgs and (msgs[-1].get("text") or "").strip() == cur:
        msgs.pop()
    msgs = msgs[-limit:]
    if not msgs:
        return ""
    return "\n".join(f"{_speaker(m, bot_name)}：{_body(m)}" for m in msgs)


def build_prompt(
    data: dict,
    cleaned_text: str,
    history: list[dict] | None,
    bot_name: str,
    *,
    history_limit: int = 8,
) -> str:
    """Assemble the full context-rich prompt sent to ``claude -p``.

    ``cleaned_text`` is the user's message with the ``@bot`` token stripped.
    ``data`` is the raw WS ``message.new`` payload (sender/group/mentions, and —
    once Wisdom supplies it — ``quoted_text``).
    """
    conv_type = data.get("conversation_type") or "private"
    conv_name = data.get("conversation_name") or data.get("target") or ""
    sender = data.get("sender_name") or data.get("sender") or "对方"
    quoted = (data.get("quoted_text") or data.get("quote_text") or "").strip()

    lines: list[str] = []
    if conv_type == "group":
        lines.append(
            f"[场景] 这是微信群「{conv_name}」里的群聊。"
            if conv_name
            else "[场景] 这是一个微信群聊。"
        )
        lines.append(f"[发消息的人] {sender}")
        at_line = "你被 @ 了。"
        others = other_mentions(data.get("mentions"), bot_name)
        if others:
            at_line += "（同时被 @ 的还有：" + "、".join(others) + "）"
        lines.append(f"[提及] {at_line}")
    else:
        lines.append("[场景] 这是一对一的微信私聊。")
        lines.append(f"[发消息的人] {sender}")

    if quoted:
        lines.append(f"[对方引用的消息] {quoted}")

    hist = format_history(
        history, bot_name, current_text=data.get("text") or "", limit=history_limit
    )
    if hist:
        lines.append("[最近的聊天记录(从旧到新)]\n" + hist)

    lines.append(f"[需要你回复的消息] {cleaned_text}")
    lines.append(
        "请直接给出要发回微信的回复内容本身,自然、口语化,不要复述上面的上下文,也不要说明你在做什么。"
    )
    return "\n".join(lines)
