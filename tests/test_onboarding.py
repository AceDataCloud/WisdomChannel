"""Tests for the customer-onboarding orchestration (scenario ④)."""

import os
import tempfile
from unittest.mock import AsyncMock, patch

os.environ.setdefault("WECHAT_STATE_DIR", tempfile.mkdtemp(prefix="wc-onboard-test-"))

from wisdom_channel.onboarding import onboard_customer

_QH = "wisdom_channel.onboarding.api"


def _ok(result: dict | None = None) -> dict:
    return {"id": "t1", "status": "succeeded", "result": result or {}}


def _mocks(create_result=None):
    """Patch the client calls onboarding makes; return the patcher context vars."""
    create = AsyncMock(return_value=_ok(create_result or {"created": True, "selected": []}))
    rename = AsyncMock(return_value=_ok({"renamed": True}))
    invite = AsyncMock(return_value=_ok({"invited": True}))
    send = AsyncMock(return_value={"id": "m1"})
    return create, rename, invite, send


async def test_empty_customer_is_rejected():
    result = await onboard_customer("   ")
    assert result["ok"] is False


async def test_requires_at_least_one_support_member():
    # Only the customer, no support members -> can't form a ≥2-member group.
    result = await onboard_customer("张三", support_members=[])
    assert result["ok"] is False
    assert "support" in result["error"].lower()


async def test_happy_path_create_rename_invite_welcome():
    create, rename, invite, send = _mocks({"created": True, "selected": ["张三", "客服A"]})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        result = await onboard_customer(
            "张三",
            support_members=["客服A"],
            big_group="Ace 客户大群",
            welcome="欢迎 {customer}!",
        )
    assert result["ok"] is True
    assert result["group"] == "张三专属客服群"
    # create with customer + support
    create.assert_awaited_once_with(["张三", "客服A"])
    # rename the auto-named group ("张三、客服A") to the target name
    rename.assert_awaited_once_with("张三、客服A", "张三专属客服群")
    # customer added to the big group
    invite.assert_awaited_once_with("Ace 客户大群", ["张三"])
    # welcome posted into the (renamed) support group, with {customer} filled
    send.assert_awaited_once_with("张三专属客服群", "欢迎 张三!")


async def test_no_big_group_no_welcome_skips_those_steps():
    create, rename, invite, send = _mocks({"created": True, "selected": ["张三", "客服A"]})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        result = await onboard_customer("张三", support_members=["客服A"], big_group="", welcome="")
    assert result["ok"] is True
    invite.assert_not_awaited()
    send.assert_not_awaited()


async def test_prefers_explicit_created_group_name_for_rename():
    # If Wisdom ever returns the created group's name, use it instead of the
    # reconstructed auto-name.
    create, rename, invite, send = _mocks({"created": True, "name": "临时群名XYZ"})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        await onboard_customer("张三", support_members=["客服A"], big_group="", welcome="")
    rename.assert_awaited_once_with("临时群名XYZ", "张三专属客服群")


async def test_create_failure_aborts_before_rename():
    create, rename, invite, send = _mocks({"created": False, "selected": []})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        result = await onboard_customer("张三", support_members=["客服A"])
    assert result["ok"] is False
    rename.assert_not_awaited()


async def test_custom_name_template():
    create, rename, invite, send = _mocks({"created": True, "selected": ["张三", "客服A"]})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        result = await onboard_customer(
            "张三", support_members=["客服A"], group_name_template="VIP-{customer}", welcome=""
        )
    assert result["group"] == "VIP-张三"
    rename.assert_awaited_once_with("张三、客服A", "VIP-张三")


async def test_bad_name_template_is_rejected():
    # A wrong placeholder / stray brace in the admin template must not crash.
    create, rename, _invite, _send = _mocks({"created": True, "selected": ["张三", "客服A"]})
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
    ):
        result = await onboard_customer(
            "张三", support_members=["客服A"], group_name_template="{name}群"
        )
    assert result["ok"] is False
    create.assert_not_awaited()  # rejected before any side effect


async def test_unconfirmed_rename_skips_welcome_and_flags():
    create, rename, invite, send = _mocks({"created": True, "selected": ["张三", "客服A"]})
    rename.return_value = _ok({"renamed": False})  # rename not confirmed
    with (
        patch(f"{_QH}.create_group", create),
        patch(f"{_QH}.rename_group", rename),
        patch(f"{_QH}.invite_to_group", invite),
        patch(f"{_QH}.send_message", send),
    ):
        result = await onboard_customer(
            "张三", support_members=["客服A"], welcome="欢迎 {customer}"
        )
    assert result["ok"] is True  # group was still created
    assert result["rename_confirmed"] is False
    # welcome must NOT be sent to a guessed name when the rename isn't confirmed
    send.assert_not_awaited()
    assert result["steps"]["welcome"].startswith("skipped")
