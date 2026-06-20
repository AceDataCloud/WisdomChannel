"""Access control for the WeChat channel — contact allowlist & message filtering."""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from loguru import logger

from wisdom_channel.config import ACCESS_FILE, STATE_DIR

_VALID_POLICIES = {"all", "allowlist", "disabled"}


def _default_access() -> dict[str, Any]:
    return {
        "policy": "all",  # all | allowlist | disabled
        "allowFrom": [],  # contact names / wechat IDs
        "admins": [],  # admin contact names — fully trusted, can issue commands
    }


def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    """Validate + coerce a parsed access dict into the canonical shape."""
    policy = parsed.get("policy", "all")
    if policy not in _VALID_POLICIES:
        logger.warning("invalid policy {!r} in access.json, defaulting to 'all'", policy)
        policy = "all"

    def _str_list(v: Any) -> list[str]:
        return [str(x) for x in v if str(x).strip()] if isinstance(v, list) else []

    return {
        "policy": policy,
        "allowFrom": _str_list(parsed.get("allowFrom")),
        "admins": _str_list(parsed.get("admins")),
    }


def load_access() -> dict[str, Any]:
    """Read access.json, returning validated defaults if absent or corrupt."""
    try:
        parsed = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("access.json is not an object")
        result = _normalize(parsed)
        logger.debug(
            "loaded access: policy={}, allowFrom={}, admins={}",
            result["policy"],
            result["allowFrom"],
            result["admins"],
        )
        return result
    except FileNotFoundError:
        logger.debug("no access.json at {}, using defaults (policy=all)", ACCESS_FILE)
        return _default_access()
    except (json.JSONDecodeError, ValueError, KeyError):
        # Corrupt file — move aside and start fresh
        backup = ACCESS_FILE.with_suffix(f".corrupt-{int(time.time())}")
        with contextlib.suppress(OSError):
            ACCESS_FILE.rename(backup)
        logger.warning("access.json corrupt, moved to {}, using defaults", backup)
        return _default_access()


def save_access(access: dict[str, Any]) -> None:
    """Atomically write access.json."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ACCESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(access, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ACCESS_FILE)
    logger.info("saved access: {}", json.dumps(access, ensure_ascii=False))


def _candidates(sender: str | list[str] | tuple[str, ...]) -> list[str]:
    """Normalize a sender into the identifiers to match against the allowlist.

    A caller may pass a single name, or several candidates such as
    [display_name, wechat_id] — a match on ANY of them counts. The wechat_id is
    stable and unspoofable, so it is the preferred identifier (esp. for admins)."""
    if isinstance(sender, str):
        return [sender] if sender else []
    return [str(s) for s in sender if str(s).strip()]


def is_allowed(sender: str | list[str], access: dict[str, Any] | None = None) -> bool:
    """Whether a sender may pass the gate. `sender` may be one identifier or a
    list of candidates (e.g. [display_name, wechat_id]); allowed if ANY matches."""
    if access is None:
        access = load_access()
    policy = access.get("policy", "all")
    if policy == "disabled":
        logger.info("gate: REJECT {} (policy=disabled)", sender)
        return False
    if policy == "all":
        return True
    # allowlist mode — match any candidate against allowFrom ∪ admins
    allowed_set = set(access.get("allowFrom", [])) | set(access.get("admins", []))
    cands = _candidates(sender)
    allowed = any(c in allowed_set for c in cands)
    if not allowed:
        logger.info("gate: REJECT {} (not in allowlist)", cands)
    return allowed


def get_trust_level(sender: str | list[str], access: dict[str, Any] | None = None) -> str:
    """Return 'admin' if any sender candidate is in the admins list, else 'normal'."""
    if access is None:
        access = load_access()
    admins = set(access.get("admins", []))
    return "admin" if any(c in admins for c in _candidates(sender)) else "normal"
