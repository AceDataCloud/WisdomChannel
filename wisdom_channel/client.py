"""Async HTTP client for the Wisdom REST API."""

from __future__ import annotations

import httpx
from loguru import logger

from wisdom_channel.config import WISDOM_API_TOKEN, WISDOM_API_URL


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if WISDOM_API_TOKEN:
        h["Authorization"] = f"Bearer {WISDOM_API_TOKEN}"
    return h


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        logger.info("creating httpx client → {}", WISDOM_API_URL)
        _client = httpx.AsyncClient(
            base_url=WISDOM_API_URL,
            headers=_headers(),
            timeout=30.0,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        logger.debug("closing httpx client")
        await _client.aclose()
        _client = None


async def get_status() -> dict:
    logger.debug("GET /api/status")
    r = await get_client().get("/api/status")
    logger.debug("GET /api/status → {}", r.status_code)
    r.raise_for_status()
    return r.json()


async def get_account() -> dict:
    """GET /api/account — returns logged-in WeChat account info (nickname, etc.)."""
    logger.debug("GET /api/account")
    r = await get_client().get("/api/account")
    logger.debug("GET /api/account → {}", r.status_code)
    r.raise_for_status()
    return r.json()


async def send_message(target: str, text: str, **kwargs: str | None) -> dict:
    payload: dict[str, str | list[str]] = {"target": target, "type": "text", "text": text}
    if kwargs.get("image_url"):
        payload["type"] = "image"
        payload["image_url"] = kwargs["image_url"]  # type: ignore[assignment]
    if kwargs.get("file_url"):
        payload["type"] = "file"
        payload["file_url"] = kwargs["file_url"]  # type: ignore[assignment]
    if kwargs.get("video_url"):
        payload["type"] = "video"
        payload["video_url"] = kwargs["video_url"]  # type: ignore[assignment]
    logger.info(
        "POST /api/messages/send → target={}, type={}, text={}",
        target,
        payload["type"],
        text[:80],
    )
    r = await get_client().post("/api/messages/send", json=payload)
    logger.info("POST /api/messages/send → {}: {}", r.status_code, r.text[:200])
    r.raise_for_status()
    return r.json()


async def list_contacts(query: str | None = None, contact_type: str | None = None) -> dict:
    params: dict[str, str] = {}
    if query:
        params["query"] = query
    if contact_type:
        params["type"] = contact_type
    logger.debug("GET /api/contacts params={}", params)
    r = await get_client().get("/api/contacts", params=params)
    logger.debug("GET /api/contacts → {}", r.status_code)
    r.raise_for_status()
    return r.json()


async def list_conversations(limit: int = 20) -> dict:
    logger.debug("GET /api/conversations limit={}", limit)
    r = await get_client().get("/api/conversations", params={"limit": limit})
    logger.debug("GET /api/conversations → {}", r.status_code)
    r.raise_for_status()
    return r.json()


async def get_messages(target: str, limit: int = 20) -> dict:
    """Get messages for a contact by name.

    Flow: GET /api/conversations → find matching name → GET /api/messages?conversation_id=...
    """
    logger.debug("get_messages: resolving conversation for {}", target)
    convs = await list_conversations(limit=100)
    conv_list = convs.get("conversations", [])
    conv_id = None
    for c in conv_list:
        if c.get("name") == target:
            conv_id = c.get("id")
            break
    if not conv_id:
        # Try partial match
        for c in conv_list:
            if target.lower() in (c.get("name") or "").lower():
                conv_id = c.get("id")
                break
    if not conv_id:
        logger.warning("get_messages: no conversation found for {}", target)
        return {"error": f"No conversation found for '{target}'", "messages": []}

    logger.debug("get_messages: resolved {} → conversation_id={}", target, conv_id)
    r = await get_client().get(
        "/api/messages",
        params={"conversation_id": conv_id, "limit": limit, "order": "desc"},
    )
    logger.debug("GET /api/messages → {}", r.status_code)
    r.raise_for_status()
    return r.json()


# --- UI tasks (group ops are queued and run asynchronously on the CVM) --------


async def wait_task(task_id: str, *, timeout: float = 90.0, poll: float = 1.0) -> dict:
    """Poll GET /api/tasks/{id} until it finishes; return the final UiTaskOut.

    Group create/rename/invite are queued UI tasks (202 + task id). Onboarding
    is sequential and must wait for each step to actually complete before the
    next, so we poll to a terminal status here.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        r = await get_client().get(f"/api/tasks/{task_id}")
        r.raise_for_status()
        task = r.json()
        if task.get("status") in ("succeeded", "failed"):
            return task
        await asyncio.sleep(poll)
    logger.warning("wait_task: {} timed out after {}s", task_id, timeout)
    return {"id": task_id, "status": "timeout"}


async def _post_and_wait(path: str, payload: dict, *, timeout: float = 90.0) -> dict:
    logger.info("POST {} payload={}", path, payload)
    r = await get_client().post(path, json=payload)
    logger.info("POST {} → {}: {}", path, r.status_code, r.text[:200])
    r.raise_for_status()
    task = r.json()
    tid = task.get("id")
    if not tid:
        return task
    return await wait_task(tid, timeout=timeout)


async def create_group(members: list[str]) -> dict:
    """POST /api/groups — start a group with ≥2 members; waits for completion.

    Result (in the returned UiTaskOut's ``result``) is
    ``{"created": bool, "selected": [...], "requested": [...]}``.
    """
    return await _post_and_wait("/api/groups", {"members": members})


async def rename_group(group: str, new_name: str) -> dict:
    """POST /api/groups/rename — rename an existing group; waits for completion."""
    return await _post_and_wait("/api/groups/rename", {"group": group, "new_name": new_name})


async def invite_to_group(group: str, members: list[str]) -> dict:
    """POST /api/groups/invite — add members to an existing group; waits for completion."""
    return await _post_and_wait("/api/groups/invite", {"group": group, "members": members})
