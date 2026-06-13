"""Wisdom Channel — bridges WeChat messages (via Wisdom API) to Claude Code."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("wisdom-channel")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
