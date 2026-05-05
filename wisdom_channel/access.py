"""Access control for the WeChat channel — contact allowlist & message filtering."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from wisdom_channel.config import ACCESS_FILE, STATE_DIR


def _default_access() -> dict[str, Any]:
    return {
        "policy": "all",  # all | allowlist | disabled
        "allowFrom": [],  # contact names / wechat IDs
        "admins": [],  # admin contact names — fully trusted, can issue commands
    }


def load_access() -> dict[str, Any]:
    """Read access.json, returning defaults if absent or corrupt."""
    try:
        raw = ACCESS_FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        result = {
            "policy": parsed.get("policy", "all"),
            "allowFrom": parsed.get("allowFrom", []),
            "admins": parsed.get("admins", []),
        }
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
    except (json.JSONDecodeError, KeyError):
        # Corrupt file — move aside and start fresh
        backup = ACCESS_FILE.with_suffix(f".corrupt-{int(__import__('time').time())}")
        try:
            ACCESS_FILE.rename(backup)
        except OSError:
            pass
        logger.warning("access.json corrupt, moved to {}, using defaults", backup)
        return _default_access()


def save_access(access: dict[str, Any]) -> None:
    """Atomically write access.json."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ACCESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(access, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ACCESS_FILE)
    logger.info("saved access: {}", json.dumps(access, ensure_ascii=False))


def is_allowed(sender: str, access: dict[str, Any] | None = None) -> bool:
    """Check whether a sender is allowed through the gate."""
    if access is None:
        access = load_access()
    policy = access.get("policy", "all")
    if policy == "disabled":
        logger.info("gate: REJECT '{}' (policy=disabled)", sender)
        return False
    if policy == "all":
        return True
    # allowlist mode
    allow_from = access.get("allowFrom", [])
    admins = access.get("admins", [])
    allowed = sender in allow_from or sender in admins
    if not allowed:
        logger.info("gate: REJECT '{}' (not in allowlist: {})", sender, allow_from)
    return allowed


def get_trust_level(sender: str, access: dict[str, Any] | None = None) -> str:
    """Return 'admin' if sender is in the admins list, else 'normal'."""
    if access is None:
        access = load_access()
    admins = access.get("admins", [])
    return "admin" if sender in admins else "normal"
