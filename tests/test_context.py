"""Unit tests for the context/prompt builder and @-mention parsing.

Pure functions — no network, no WeChat. Sets WECHAT_STATE_DIR before import so
config/logging never touch real state.
"""

import os
import tempfile

os.environ.setdefault("WECHAT_STATE_DIR", tempfile.mkdtemp(prefix="wc-test-"))

from wisdom_channel.context import (
    build_prompt,
    format_history,
    is_at_me,
    other_mentions,
    strip_at_mention,
)

BOT = "小智"
_SEP = " "  # U+2005, the separator WeChat puts after an @name


# ── @-mention detection ──────────────────────────────────────────────────────
def test_at_me_via_mentions_list():
    assert is_at_me("随便什么", ["小智", "张三"], BOT) is True
    assert is_at_me("随便什么", ["张三"], BOT) is False


def test_at_me_via_text_u2005_separator():
    # WeChat real form: "@小智<U+2005>你好"
    assert is_at_me(f"@{BOT}{_SEP}你好", None, BOT) is True


def test_at_me_via_text_plain_space_and_eol():
    assert is_at_me(f"@{BOT} 在吗", None, BOT) is True
    assert is_at_me(f"在吗 @{BOT}", None, BOT) is True


def test_at_someone_else_is_not_at_me():
    assert is_at_me(f"@张三{_SEP}你好", None, BOT) is False


def test_at_me_unknown_bot_name_matches_any_at():
    assert is_at_me("@谁都行 hi", None, "") is True
    assert is_at_me("没有艾特", None, "") is False


def test_strip_at_mention_u2005():
    assert strip_at_mention(f"@{BOT}{_SEP}今天天气如何", BOT) == "今天天气如何"


def test_strip_at_mention_keeps_other_ats():
    # Only the bot's @ is removed; an @ to someone else stays as context.
    out = strip_at_mention(f"@{BOT}{_SEP}帮我问问 @张三{_SEP}", BOT)
    assert BOT not in out
    assert "张三" in out


def test_strip_at_mention_no_bot_name_drops_leading_at():
    assert strip_at_mention(f"@某人{_SEP}你好", "") == "你好"


def test_other_mentions_excludes_bot_and_dedupes():
    assert other_mentions(["小智", "张三", "张三", "李四"], BOT) == ["张三", "李四"]
    assert other_mentions(None, BOT) == []


# ── history rendering ─────────────────────────────────────────────────────────
def _msg(sender, text, direction="inbound", mtype="text"):
    return {"sender_name": sender, "text": text, "direction": direction, "type": mtype}


def test_format_history_chronological_and_speaker_labels():
    # API returns newest-first; we render oldest→newest, bot labelled distinctly.
    msgs = [
        _msg(BOT, "稍等", direction="outbound"),  # newest
        _msg("张三", "在吗"),
        _msg("李四", "大家好"),  # oldest
    ]
    out = format_history(msgs, BOT)
    lines = out.splitlines()
    assert lines[0] == "李四：大家好"
    assert lines[1] == "张三：在吗"
    assert lines[2] == "你(机器人)：稍等"


def test_format_history_drops_duplicate_current_message():
    msgs = [_msg("张三", "你好"), _msg("李四", "早")]  # newest first; current == 你好
    out = format_history(msgs, BOT, current_text="你好")
    assert "你好" not in out
    assert "早" in out


def test_format_history_non_text_placeholder():
    out = format_history([_msg("张三", "", mtype="image")], BOT)
    assert out == "张三：[图片]"


def test_format_history_respects_limit():
    msgs = [_msg("u", str(i)) for i in range(20)]
    out = format_history(msgs, BOT, limit=3)
    assert len(out.splitlines()) == 3


# ── full prompt assembly ──────────────────────────────────────────────────────
def test_build_prompt_group_includes_scene_sender_mentions_history():
    data = {
        "conversation_type": "group",
        "conversation_name": "AI 交流群",
        "sender_name": "张三",
        "mentions": ["小智", "李四"],
        "text": f"@{BOT}{_SEP}帮我总结下",
    }
    history = [_msg("李四", "刚发了篇文章")]
    prompt = build_prompt(data, "帮我总结下", history, BOT)
    assert "群「AI 交流群」" in prompt
    assert "[发消息的人] 张三" in prompt
    assert "你被 @ 了" in prompt
    assert "李四" in prompt  # other mention listed
    assert "刚发了篇文章" in prompt  # history injected
    assert "[需要你回复的消息] 帮我总结下" in prompt


def test_build_prompt_private_no_mention_block():
    data = {"conversation_type": "private", "sender_name": "王五", "text": "在吗"}
    prompt = build_prompt(data, "在吗", [], BOT)
    assert "私聊" in prompt
    assert "[提及]" not in prompt
    assert "[需要你回复的消息] 在吗" in prompt


def test_build_prompt_includes_quote_when_present():
    data = {
        "conversation_type": "group",
        "conversation_name": "G",
        "sender_name": "张三",
        "mentions": ["小智"],
        "text": f"@{BOT}{_SEP}这个怎么弄",
        "quoted_text": "明天上线",
    }
    prompt = build_prompt(data, "这个怎么弄", [], BOT)
    assert "[对方引用的消息] 明天上线" in prompt


# ── trust resolution (security boundary) ──────────────────────────────────────
_ADMIN_ACCESS = {"policy": "allowlist", "allowFrom": [], "admins": ["boss"]}


def test_admin_gets_admin_trust_in_private():
    from wisdom_channel.bridge import _resolve_trust

    assert _resolve_trust("private", ["boss"], _ADMIN_ACCESS) == "admin"


def test_admin_downgraded_to_normal_in_group():
    # Security: tool-bearing admin mode must NOT be reachable from a group chat,
    # even for an admin — a group is a shared, lower-trust surface.
    from wisdom_channel.bridge import _resolve_trust

    assert _resolve_trust("group", ["boss"], _ADMIN_ACCESS) == "normal"


def test_normal_user_stays_normal_in_private():
    from wisdom_channel.bridge import _resolve_trust

    assert _resolve_trust("private", ["someone"], _ADMIN_ACCESS) == "normal"
