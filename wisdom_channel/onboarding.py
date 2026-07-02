"""Customer onboarding orchestration (scenario ④).

When a new customer is added on WeChat, spin up a dedicated support group:

    create group  →  rename to "{customer}专属客服群"  →  (optional) add the
    customer to a shared big group  →  (optional) post a welcome message

Trigger: a Wisdom ``friend.added`` WebSocket event (once Wisdom emits one — see
the ``friend.added`` branch in bridge.py) or the manual
``wisdom-channel onboard <customer>`` command. Everything is config-driven via
the ``ONBOARDING_*`` settings.

Group targeting note: Wisdom's ``create_group`` returns
``{created, selected, requested}`` but not the new group's name, and WeChat
auto-names a fresh group by joining member display names with "、". We derive
that auto-name to target the rename. If Wisdom later returns the created group's
name directly, prefer that (see ``_created_group_name``).
"""

from __future__ import annotations

from loguru import logger

from wisdom_channel import client as api
from wisdom_channel.config import (
    ONBOARDING_BIG_GROUP,
    ONBOARDING_GROUP_NAME_TEMPLATE,
    ONBOARDING_SUPPORT_MEMBERS,
    ONBOARDING_WELCOME,
)


def _task_result(task: dict) -> dict:
    """Extract the UiTaskOut ``result`` payload (or {} on failure/absence)."""
    if not isinstance(task, dict):
        return {}
    res = task.get("result")
    return res if isinstance(res, dict) else {}


def _created_group_name(create_task: dict, members: list[str]) -> str:
    """Best-effort name of the just-created group, to target the rename.

    Prefer an explicit name if Wisdom ever returns one; otherwise reconstruct
    WeChat's auto-name (member display names joined by "、").
    """
    res = _task_result(create_task)
    explicit = res.get("name") or res.get("group") or res.get("group_name")
    if explicit:
        return str(explicit)
    selected = res.get("selected") or members
    return "、".join(str(m) for m in selected)


async def onboard_customer(
    customer: str,
    *,
    support_members: list[str] | None = None,
    group_name_template: str | None = None,
    big_group: str | None = None,
    welcome: str | None = None,
) -> dict:
    """Run the onboarding flow for *customer*. Never raises; returns a summary.

    Overrides default to the ``ONBOARDING_*`` config, so tests and callers can
    inject values without mutating the environment.
    """
    customer = (customer or "").strip()
    if not customer:
        return {"ok": False, "error": "empty customer name"}

    support = list(support_members if support_members is not None else ONBOARDING_SUPPORT_MEMBERS)
    template = group_name_template or ONBOARDING_GROUP_NAME_TEMPLATE
    big = (big_group if big_group is not None else ONBOARDING_BIG_GROUP) or ""
    welcome_text = (welcome if welcome is not None else ONBOARDING_WELCOME) or ""

    # WeChat needs ≥2 members to start a group: the customer + ≥1 support member.
    members = [customer, *[m for m in support if m and m != customer]]
    if len(members) < 2:
        return {
            "ok": False,
            "error": "need the customer plus at least one ONBOARDING_SUPPORT_MEMBERS entry",
            "members": members,
        }

    # The template is admin-set; a stray brace / wrong placeholder must not crash
    # onboarding (it would escape the bridge's fire-and-forget task silently).
    try:
        target_name = template.format(customer=customer)
    except (KeyError, ValueError, IndexError) as e:
        return {"ok": False, "error": f"bad group-name template {template!r}: {e}"}
    summary: dict = {"customer": customer, "group": target_name, "steps": {}}
    logger.info("onboard: customer={!r} members={} -> group={!r}", customer, members, target_name)

    # 1. Create the group.
    create_task = await api.create_group(members)
    summary["steps"]["create"] = create_task.get("status")
    created = _task_result(create_task).get("created", create_task.get("status") == "succeeded")
    if not created:
        summary["ok"] = False
        summary["error"] = "group creation failed"
        return summary

    # 2. Rename the auto-named group to the target name.
    auto_name = _created_group_name(create_task, members)
    rename_task = await api.rename_group(auto_name, target_name)
    renamed = _task_result(rename_task).get("renamed", rename_task.get("status") == "succeeded")
    summary["steps"]["rename"] = rename_task.get("status")
    summary["rename_confirmed"] = renamed
    if not renamed:
        # We can't tell whether the rename genuinely failed (group is still
        # auto_name) or just wasn't confirmed (e.g. a poll timeout while WeChat
        # DID rename it), so we must NOT guess a name for the welcome below.
        logger.warning("onboard: rename {!r} -> {!r} not confirmed", auto_name, target_name)

    # 3. Optionally add the customer to the shared big group (name-independent).
    if big:
        invite_task = await api.invite_to_group(big, [customer])
        summary["steps"]["invite_big_group"] = invite_task.get("status")

    # 4. Optional welcome — only when we know the group name (rename confirmed),
    # otherwise we'd risk sending to a wrong/nonexistent name.
    if welcome_text:
        if not renamed:
            summary["steps"]["welcome"] = "skipped (rename unconfirmed)"
        else:
            try:
                await api.send_message(target_name, welcome_text.format(customer=customer))
                summary["steps"]["welcome"] = "sent"
            except Exception as e:  # welcome is a nice-to-have — never fail on it
                logger.warning("onboard: welcome send failed: {!r}", e)
                summary["steps"]["welcome"] = "failed"

    # The group was created (the essential outcome). ``rename_confirmed`` tells
    # the caller whether the naming step is verified.
    summary["ok"] = True
    logger.info(
        "onboard: done customer={!r} group={!r} renamed={} steps={}",
        customer,
        target_name,
        renamed,
        summary["steps"],
    )
    return summary
