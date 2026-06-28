"""Smoke tests for package import and v3 access-control decisions."""

import os
import tempfile

os.environ.setdefault("WECHAT_STATE_DIR", tempfile.mkdtemp(prefix="wc-test-"))

import wisdom_channel
from wisdom_channel.access import (
    ROLE_DENY,
    ROLE_NORMAL,
    ROLE_SUPER_ADMIN,
    load_access,
    resolve_access,
)


def _access():
    return {
        "version": 3,
        "enabled": True,
        "users": {
            "root": {"role": ROLE_SUPER_ADMIN},
            "ops": {"role": "admin"},
            "alice": {"role": ROLE_NORMAL},
        },
        "private": {"enabled": True, "default_role": ROLE_DENY, "prompt": "private prompt"},
        "groups": {
            "Ops": {"enabled": True, "default_role": ROLE_NORMAL, "prompt": "ops prompt", "members": {}},
            "Locked": {"enabled": True, "default_role": ROLE_DENY, "prompt": "", "members": {}},
        },
    }


def test_version_is_str():
    assert isinstance(wisdom_channel.__version__, str)
    assert wisdom_channel.__version__


def test_empty_default_denies_private_and_groups():
    assert resolve_access(sender_id="root", conversation_type="private", access={}).allowed is False
    assert (
        resolve_access(
            sender_id="root",
            conversation_name="Ops",
            conversation_type="group",
            access={},
        ).allowed
        is False
    )


def test_group_default_role_allows_normal_chat_only():
    decision = resolve_access(
        sender_name="Bob",
        sender_id="wxid_bob",
        conversation_name="Ops",
        conversation_type="group",
        access=_access(),
    )
    assert decision.allowed is True
    assert decision.role == ROLE_NORMAL
    assert decision.allow_tools is False
    assert "ops prompt" in decision.prompt


def test_unknown_private_is_blocked():
    decision = resolve_access(sender_name="Bob", sender_id="wxid_bob", conversation_type="private", access=_access())
    assert decision.allowed is False
    assert decision.reason == "private sender not allowed"


def test_super_admin_requires_stable_sender_id_not_display_name():
    spoofed = resolve_access(
        sender_name="root",
        sender_id="wxid_attacker",
        conversation_name="Ops",
        conversation_type="group",
        access=_access(),
    )
    assert spoofed.allowed is True
    assert spoofed.role == ROLE_NORMAL
    assert spoofed.allow_tools is False

    real = resolve_access(
        sender_name="whatever",
        sender_id="root",
        conversation_name="Ops",
        conversation_type="group",
        access=_access(),
    )
    assert real.allowed is True
    assert real.role == ROLE_SUPER_ADMIN
    assert real.allow_tools is True


def test_unknown_conversation_type_is_denied():
    decision = resolve_access(sender_id="root", conversation_type="room", access=_access())
    assert decision.allowed is False
    assert decision.reason == "unknown conversation_type"


def test_admin_private_only_falls_back_to_group_default():
    group = resolve_access(
        sender_id="ops",
        conversation_name="Ops",
        conversation_type="group",
        access=_access(),
    )
    assert group.allowed is True
    assert group.role == ROLE_NORMAL
    assert group.allow_tools is False

    private = resolve_access(sender_id="ops", conversation_type="private", access=_access())
    assert private.allowed is True
    assert private.role == "admin"
    assert private.allow_tools is True


def test_group_fallback_does_not_carry_admin_user_prompt():
    access = _access()
    access["users"]["ops"]["prompt"] = "secret operator prompt"
    group = resolve_access(sender_id="ops", conversation_name="Ops", conversation_type="group", access=access)
    assert group.role == ROLE_NORMAL
    assert "secret operator prompt" not in group.prompt


def test_group_member_override_can_deny_or_promote():
    access = _access()
    access["groups"]["Ops"]["members"] = {
        "alice": {"role": ROLE_DENY},
        "root": {"role": ROLE_SUPER_ADMIN, "prompt": "member prompt"},
    }
    denied = resolve_access(sender_id="alice", conversation_name="Ops", conversation_type="group", access=access)
    assert denied.allowed is False

    promoted = resolve_access(sender_id="root", conversation_name="Ops", conversation_type="group", access=access)
    assert promoted.allowed is True
    assert promoted.role == ROLE_SUPER_ADMIN
    assert "member prompt" in promoted.prompt


def test_config_typos_fail_closed():
    bad_context = resolve_access(
        sender_id="root",
        conversation_name="Ops",
        conversation_type="group",
        access={
            "roles": {ROLE_SUPER_ADMIN: {"allow_tools": True, "contexts": ["groupp"]}},
            "users": {"root": {"role": ROLE_SUPER_ADMIN}},
            "groups": {"Ops": {"enabled": True, "default_role": ROLE_NORMAL}},
        },
    )
    assert bad_context.allowed is True
    assert bad_context.role == ROLE_NORMAL

    bad_role = resolve_access(
        sender_id="anyone",
        conversation_name="Ops",
        conversation_type="group",
        access={"groups": {"Ops": {"enabled": True, "default_role": "typo"}}},
    )
    assert bad_role.allowed is False


def test_global_disable_blocks_everything():
    access = _access()
    access["enabled"] = False
    decision = resolve_access(sender_id="root", conversation_name="Ops", conversation_type="group", access=access)
    assert decision.allowed is False
    assert decision.reason == "access disabled"


def test_trust_enforced_in_bridge_args():
    from wisdom_channel.bridge import _claude_args

    normal = _claude_args("claude", "hi", "sonnet", ROLE_NORMAL, False)
    super_admin = _claude_args("claude", "hi", "sonnet", ROLE_SUPER_ADMIN, True)
    assert "--tools" in normal and normal[normal.index("--tools") + 1] == ""
    assert "--dangerously-skip-permissions" not in normal
    assert "--tools" not in super_admin
    assert "--dangerously-skip-permissions" in super_admin


def test_sender_identity_requires_sender_id():
    from wisdom_channel.access import trusted_sender_id

    assert trusted_sender_id({"sender": "sunbitty", "sender_name": "CQC"}) == ""
    assert trusted_sender_id({"sender": "sunbitty"}) == ""
    assert trusted_sender_id({"sender_id": "wxid_admin"}) == "wxid_admin"


def test_invalid_boolean_config_fails_closed():
    access = _access()
    access["enabled"] = "yes"
    assert resolve_access(sender_id="root", conversation_type="private", access=access).allowed is False

    access = _access()
    access["roles"] = {}
    access["roles"][ROLE_SUPER_ADMIN] = {"allow_tools": "yes", "contexts": ["private"]}
    decision = resolve_access(sender_id="root", conversation_type="private", access=access)
    assert decision.allowed is True
    assert decision.allow_tools is False


def test_builtin_role_override_does_not_inherit_tool_grants():
    access = _access()
    access["roles"] = {ROLE_SUPER_ADMIN: {"prompt": "typo override missing grants"}}
    decision = resolve_access(sender_id="root", conversation_type="private", access=access)
    assert decision.allowed is False


def test_access_cli_edits_v3_policy(monkeypatch, tmp_path):
    import wisdom_channel.access as access_mod
    from wisdom_channel.access_cli import run

    access_file = tmp_path / "access.json"
    monkeypatch.setattr(access_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(access_mod, "ACCESS_FILE", access_file)

    assert run(["allow-group", "Ops Group"]) == 0
    assert run(["add-super-admin", "sunbitty"]) == 0
    assert run(["disable"]) == 0
    saved = load_access()
    assert "Ops Group" in saved["groups"]
    assert saved["users"]["sunbitty"]["role"] == ROLE_SUPER_ADMIN
    assert saved["enabled"] is False
