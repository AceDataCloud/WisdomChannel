"""Smoke tests — exercise package import + the pure access-control logic.

Sets WECHAT_STATE_DIR to a throwaway dir before importing so the import-time
config/logging setup never touches the real ~/.claude state.
"""

import os
import tempfile

os.environ.setdefault("WECHAT_STATE_DIR", tempfile.mkdtemp(prefix="wc-test-"))

import wisdom_channel
from wisdom_channel.access import get_trust_level, is_allowed

_ALLOWLIST = {"policy": "allowlist", "allowFrom": ["Alice"], "admins": ["Bob"]}


def test_version_is_str():
    assert isinstance(wisdom_channel.__version__, str)
    assert wisdom_channel.__version__


def test_policy_all_allows_everyone():
    assert is_allowed("anyone", {"policy": "all"}) is True


def test_policy_disabled_blocks_everyone():
    assert is_allowed("Bob", {"policy": "disabled", "admins": ["Bob"]}) is False


def test_allowlist_gating():
    assert is_allowed("Alice", _ALLOWLIST) is True
    assert is_allowed("Bob", _ALLOWLIST) is True  # admins are allowed too
    assert is_allowed("Carol", _ALLOWLIST) is False


def test_trust_level():
    assert get_trust_level("Bob", _ALLOWLIST) == "admin"
    assert get_trust_level("Alice", _ALLOWLIST) == "normal"
