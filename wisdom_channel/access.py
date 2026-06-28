"""Configurable access control for the WeChat channel."""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from wisdom_channel.config import ACCESS_FILE, STATE_DIR

ROLE_DENY = "deny"
ROLE_NORMAL = "normal"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    role: str
    reason: str
    sender_id: str = ""
    sender_name: str = ""
    group: str = ""
    prompt: str = ""
    allow_tools: bool = False

    @property
    def trust_level(self) -> str:
        return self.role


def _default_roles() -> dict[str, dict[str, Any]]:
    return {
        ROLE_NORMAL: {
            "allow_tools": False,
            "contexts": ["group", "private"],
            "prompt": (
                "你正在回复普通用户。只回答公开、基础、常识、产品概念、调研类问题; "
                "不要执行命令、查询代码/文件/日志/服务器/数据库/内部配置; "
                "不要透露内部路径、主机、密钥、供应商或项目细节。"
            ),
        },
        ROLE_ADMIN: {
            "allow_tools": True,
            "contexts": ["private"],
            "prompt": "对方是管理员。仅在私聊中可按其请求协助执行项目或运维操作。",
        },
        ROLE_SUPER_ADMIN: {
            "allow_tools": True,
            "contexts": ["group", "private"],
            "prompt": (
                "对方是超级管理员,可以请求调研、项目级查询、工具调用和运维操作。"
                "仍需避免向非相关聊天泄露密钥、令牌等原始秘密。"
            ),
        },
    }


def _default_access() -> dict[str, Any]:
    return {
        "version": 3,
        "enabled": True,
        "roles": _default_roles(),
        "users": {},
        "private": {"enabled": True, "default_role": ROLE_DENY, "prompt": ""},
        "groups": {},
    }


def recommended_access() -> dict[str, Any]:
    """Example policy for CQ's current production bot; not used as package default."""
    access = _default_access()
    access["users"] = {
        "CQCcqc": {"role": ROLE_SUPER_ADMIN},
        "sunbitty": {"role": ROLE_SUPER_ADMIN},
    }
    for name in [
        "Ace Data Cloud客户群1",
        "Ace Data Cloud客户群2",
        "Ace Data Cloud客户群3",
        "Ace Data Cloud客户群4",
        "Ace Data Cloud客户群5",
        "AceDataCloud团队",
    ]:
        access["groups"][name] = {"enabled": True, "default_role": ROLE_NORMAL, "prompt": ""}
    access["groups"]["AceDataCloud团队"]["prompt"] = (
        "这是内部团队群。超级管理员可做项目级协作; 普通成员仍按 normal 限制回答。"
    )
    return access


def _str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _str_list(value: Any, default: list[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return list(default or [])
    return [_str(item) for item in value if _str(item)]


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return False


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _role_name(value: Any, roles: dict[str, Any], default: str = ROLE_DENY) -> str:
    raw = _str(value)
    role = raw or default
    if role == ROLE_DENY or role in roles:
        return role
    logger.warning("unknown role {!r} in access.json, denying", role)
    return ROLE_DENY


def _normalize_role(name: str, raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    role = _object(raw)
    base = base or {}
    contexts = _str_list(role.get("contexts"), base.get("contexts", []) if "contexts" not in role else [])
    contexts = [ctx for ctx in contexts if ctx in {"group", "private"}]
    return {
        "allow_tools": _bool(role.get("allow_tools"), bool(base.get("allow_tools", False))),
        "contexts": contexts,
        "prompt": _str(role.get("prompt")) or _str(base.get("prompt")),
        "label": _str(role.get("label")) or name,
    }


def _normalize_user(raw: Any, roles: dict[str, Any]) -> dict[str, Any]:
    user = _object(raw)
    return {
        "role": _role_name(user.get("role"), roles),
        "name": _str(user.get("name")),
        "prompt": _str(user.get("prompt")),
    }


def _normalize_group(raw: Any, roles: dict[str, Any]) -> dict[str, Any]:
    group = _object(raw)
    members = _object(group.get("members"))
    return {
        "enabled": _bool(group.get("enabled"), False),
        "default_role": _role_name(group.get("default_role"), roles, ROLE_DENY),
        "prompt": _str(group.get("prompt")),
        "members": {key: _normalize_user(value, roles) for key, value in members.items()},
    }


def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_access()
    raw_roles = _object(parsed.get("roles"))
    roles = _default_roles()
    for name, raw in raw_roles.items():
        role_name = _str(name)
        if role_name and role_name != ROLE_DENY:
            roles[role_name] = _normalize_role(role_name, raw)

    raw_private = _object(parsed.get("private"))
    raw_users = _object(parsed.get("users"))
    raw_groups = _object(parsed.get("groups"))

    return {
        "version": 3,
        "enabled": _bool(parsed.get("enabled"), defaults["enabled"]),
        "roles": roles,
        "users": {key: _normalize_user(value, roles) for key, value in raw_users.items()},
        "private": {
            "enabled": _bool(raw_private.get("enabled"), True),
            "default_role": _role_name(raw_private.get("default_role"), roles),
            "prompt": _str(raw_private.get("prompt")),
        },
        "groups": {key: _normalize_group(value, roles) for key, value in raw_groups.items()},
    }


def load_access() -> dict[str, Any]:
    """Read access.json, returning safe empty-deny defaults if absent/corrupt."""
    try:
        parsed = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("access.json is not an object")
        result = _normalize(parsed)
        logger.debug("loaded access v{} enabled={}", result["version"], result["enabled"])
        return result
    except FileNotFoundError:
        logger.debug("no access.json at {}, using empty allowlist defaults", ACCESS_FILE)
        return _default_access()
    except (json.JSONDecodeError, ValueError, KeyError):
        backup = ACCESS_FILE.with_suffix(f".corrupt-{int(time.time())}")
        with contextlib.suppress(OSError):
            ACCESS_FILE.rename(backup)
        logger.warning("access.json corrupt, moved to {}, using empty defaults", backup)
        return _default_access()


def save_access(access: dict[str, Any]) -> None:
    """Atomically write access.json after normalizing it."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ACCESS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(_normalize(access), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(ACCESS_FILE)


def _role_prompt(access: dict[str, Any], role: str) -> str:
    if role == ROLE_DENY:
        return ""
    return _str(access.get("roles", {}).get(role, {}).get("prompt"))


def _role_allows_context(access: dict[str, Any], role: str, context: str) -> bool:
    if role == ROLE_DENY:
        return False
    return context in access.get("roles", {}).get(role, {}).get("contexts", [])


def _role_allows_tools(access: dict[str, Any], role: str) -> bool:
    if role == ROLE_DENY:
        return False
    return bool(access.get("roles", {}).get(role, {}).get("allow_tools", False))


def _prompt(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def trusted_sender_id(data: dict[str, Any], access: dict[str, Any] | None = None) -> str:
    """Extract the stable sender ID. Display/name fields are never trusted."""
    return _str(data.get("sender_id"))


def _user_for(access: dict[str, Any], sender_id: str) -> dict[str, Any]:
    if not sender_id:
        return {}
    return _object(access.get("users", {}).get(sender_id))


def _deny(reason: str, sender_name: str, sender_id: str, group: str = "") -> AccessDecision:
    return AccessDecision(False, ROLE_DENY, reason, sender_id, sender_name, group)


def _allow(
    access: dict[str, Any],
    role: str,
    reason: str,
    *,
    sender_name: str,
    sender_id: str,
    group: str = "",
    prompt: str = "",
) -> AccessDecision:
    return AccessDecision(
        True,
        role,
        reason,
        sender_id,
        sender_name,
        group,
        prompt,
        _role_allows_tools(access, role),
    )


def resolve_access(
    *,
    sender_name: str = "",
    sender_id: str = "",
    conversation_name: str = "",
    conversation_type: str = "private",
    access: dict[str, Any] | None = None,
) -> AccessDecision:
    """Decide whether a message may reach Claude and under which role.

    Elevated roles are keyed by stable ``sender_id`` only. Display names can be
    used for context, never for privilege.
    """
    access = _normalize(load_access() if access is None else access)
    sender_name = _str(sender_name)
    sender_id = _str(sender_id)
    context = "group" if conversation_type == "group" else "private"
    if conversation_type not in {"group", "private"}:
        return _deny("unknown conversation_type", sender_name, sender_id, conversation_name)

    if not access.get("enabled", True):
        return _deny("access disabled", sender_name, sender_id, conversation_name)

    user = _user_for(access, sender_id)
    user_role = _role_name(user.get("role"), access["roles"]) if user else ROLE_DENY

    if context == "group":
        group_name = _str(conversation_name)
        group = _object(access.get("groups", {}).get(group_name))
        if not group or not group.get("enabled", True):
            return _deny("group not allowed", sender_name, sender_id, group_name)
        member = _object(group.get("members", {}).get(sender_id))
        if member:
            role = _role_name(member.get("role"), access["roles"])
        elif user_role != ROLE_DENY and _role_allows_context(access, user_role, "group"):
            role = user_role
        else:
            role = _role_name(group.get("default_role"), access["roles"], ROLE_NORMAL)
        if not _role_allows_context(access, role, "group"):
            return _deny(f"role {role} not allowed in group", sender_name, sender_id, group_name)
        user_prompt = _str(user.get("prompt")) if user and role == user_role else ""
        return _allow(
            access,
            role,
            f"group:{group_name}",
            sender_name=sender_name,
            sender_id=sender_id,
            group=group_name,
            prompt=_prompt(
                _role_prompt(access, role),
                _str(group.get("prompt")),
                user_prompt,
                _str(member.get("prompt")) if member else "",
            ),
        )

    private = _object(access.get("private"))
    if not private.get("enabled", True):
        return _deny("private disabled", sender_name, sender_id)
    role = user_role if user_role != ROLE_DENY else _role_name(private.get("default_role"), access["roles"])
    if role == ROLE_DENY:
        return _deny("private sender not allowed", sender_name, sender_id)
    if not _role_allows_context(access, role, "private"):
        return _deny(f"role {role} not allowed in private", sender_name, sender_id)
    return _allow(
        access,
        role,
        f"private:{sender_id or sender_name}",
        sender_name=sender_name,
        sender_id=sender_id,
        prompt=_prompt(_role_prompt(access, role), _str(private.get("prompt")), _str(user.get("prompt"))),
    )
