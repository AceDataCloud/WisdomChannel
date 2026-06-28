"""Local CLI for editing the WeChat channel access policy."""

from __future__ import annotations

import json
from typing import Any

from wisdom_channel.access import ROLE_DENY, ROLE_NORMAL, ROLE_SUPER_ADMIN, load_access, save_access


def _ensure_object(access: dict[str, Any], key: str) -> dict[str, Any]:
    value = access.setdefault(key, {})
    if not isinstance(value, dict):
        value = {}
        access[key] = value
    return value


def _ensure_group(access: dict[str, Any], name: str) -> dict[str, Any]:
    groups = _ensure_object(access, "groups")
    group = groups.setdefault(name, {"enabled": True, "default_role": ROLE_NORMAL, "prompt": "", "members": {}})
    if not isinstance(group, dict):
        group = {"enabled": True, "default_role": ROLE_NORMAL, "prompt": "", "members": {}}
        groups[name] = group
    group.setdefault("members", {})
    return group


def run(argv: list[str]) -> int:
    access = load_access()
    cmd = argv[0] if argv else "view"
    value = " ".join(argv[1:]).strip()

    if cmd == "view":
        print(json.dumps(access, indent=2, ensure_ascii=False))
        return 0
    if cmd == "enable":
        access["enabled"] = True
        save_access(access)
        print("access enabled")
        return 0
    if cmd == "disable":
        access["enabled"] = False
        save_access(access)
        print("access disabled")
        return 0
    if cmd == "allow-group" and value:
        _ensure_group(access, value)
        save_access(access)
        print(f"group allowed: {value}")
        return 0
    if cmd == "remove-group" and value:
        _ensure_object(access, "groups").pop(value, None)
        save_access(access)
        print(f"group removed: {value}")
        return 0
    if cmd == "set-group-role" and len(argv) >= 3:
        group_name = argv[1]
        role = argv[2]
        _ensure_group(access, group_name)["default_role"] = role
        save_access(access)
        print(f"group {group_name} default role set to {role}")
        return 0
    if cmd == "add-user" and len(argv) >= 3:
        user_id = argv[1]
        role = argv[2]
        name = " ".join(argv[3:]).strip()
        user = {"role": role}
        if name:
            user["name"] = name
        _ensure_object(access, "users")[user_id] = user
        save_access(access)
        print(f"user {user_id} set to role {role}")
        return 0
    if cmd == "remove-user" and value:
        _ensure_object(access, "users").pop(value, None)
        save_access(access)
        print(f"user removed: {value}")
        return 0
    if cmd == "add-super-admin" and value:
        _ensure_object(access, "users")[value] = {"role": ROLE_SUPER_ADMIN}
        save_access(access)
        print(f"super admin added: {value}")
        return 0
    if cmd == "set-private-role" and value:
        _ensure_object(access, "private")["default_role"] = value
        save_access(access)
        print(f"private default role set to {value}")
        return 0
    if cmd == "disable-private":
        _ensure_object(access, "private")["enabled"] = False
        save_access(access)
        print("private chat disabled")
        return 0
    if cmd == "enable-private":
        _ensure_object(access, "private")["enabled"] = True
        save_access(access)
        print("private chat enabled")
        return 0

    print(
        "usage: wisdom-channel access "
        "[view|enable|disable|allow-group|remove-group|set-group-role|"
        "add-user|remove-user|add-super-admin|set-private-role|"
        f"enable-private|disable-private] [value]; use role {ROLE_DENY} to deny"
    )
    return 2
