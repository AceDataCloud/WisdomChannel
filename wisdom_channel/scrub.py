"""Output-side confidentiality scrub for outbound WeChat replies.

Defence-in-depth on top of the system-prompt confidentiality rule: every reply
that leaves the channel is run through a denylist that redacts upstream provider
aliases and internal infrastructure identifiers before they reach a WeChat chat.

The denylist lives in CODE / a local config file — never in the model prompt —
so it cannot itself become a leak surface (the model never sees the list of
names it must avoid).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from loguru import logger

from wisdom_channel import config
from wisdom_channel.paths import scrub_file

# High-signal, internal-only tokens: upstream provider aliases whose appearance
# in a customer-facing reply can only be a leak. Compound/unique enough to avoid
# colliding with ordinary words. Ops add their own via scrub.json ("terms").
_DEFAULT_TERMS: tuple[str, ...] = (
    "openaihk",
    "openai-hk",
    "ttapi",
    "piapi",
    "ephone",
    "bananarouter",
    "banana-router",
    "cliproxyapi",
    "nano-banana-router",
    "oaipro",
    "aihubmix",
    "openai-sb",
)

# Regex patterns for internal infrastructure identifiers.
_DEFAULT_PATTERNS: tuple[str, ...] = (
    r"ghcr\.io/acedatacloud[^\s'\"]*",  # internal container images
    r"[a-z0-9-]+\.svc\.cluster\.local",  # k8s service DNS
    r"\b(?:ins|cls|lb|subnet|vpc|cbs)-[a-z0-9]{8}\b",  # Tencent Cloud resource ids
    r"\bplatform-(?:service|gateway|backend|frontend|publisher)[a-z0-9-]*\b",
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",  # private IPv4 (RFC1918)
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b",
    r"\b192\.168\.\d{1,3}\.\d{1,3}\b",
)


def default_terms() -> list[str]:
    return list(_DEFAULT_TERMS)


def default_patterns() -> list[str]:
    return list(_DEFAULT_PATTERNS)


@dataclass(frozen=True)
class ScrubResult:
    text: str
    hits: list[str] = field(default_factory=list)
    blocked: bool = False


@dataclass
class Matcher:
    combined_re: re.Pattern[str] | None


def compile_matcher(terms: list[str], patterns: list[str]) -> Matcher:
    """Compile ONE case-insensitive regex from literal *terms* and regex *patterns*.

    Terms match with hyphen-and-word aware boundaries so ``ttapi`` does not fire
    inside ``ttapication`` but ``openai-hk`` still matches as a whole token.
    Everything is folded into a single alternation so a single left-to-right
    ``sub`` pass handles all matches — this avoids a second pass re-scanning
    (and possibly re-matching) the replacement text. Invalid regex patterns are
    skipped (logged), never raised.
    """
    parts: list[str] = []
    clean_terms = sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)
    if clean_terms:
        alt = "|".join(re.escape(t) for t in clean_terms)
        parts.append(rf"(?<![\w-])(?:{alt})(?![\w-])")
    for p in patterns:
        if not p or not p.strip():
            continue
        try:
            re.compile(p)
        except re.error as exc:
            logger.warning("scrub: skipping invalid pattern {!r}: {}", p, exc)
            continue
        parts.append(f"(?:{p})")
    combined_re = re.compile("|".join(parts), re.IGNORECASE) if parts else None
    return Matcher(combined_re=combined_re)


def scrub(
    text: str,
    matcher: Matcher,
    *,
    mode: str = "redact",
    replacement: str = "我们的服务",
    block_message: str = "抱歉，这个问题我暂时不方便回答。",
) -> ScrubResult:
    """Redact denylisted tokens from *text* in a single left-to-right pass.

    In ``redact`` mode each match is replaced by *replacement*; in ``block`` mode
    any match replaces the whole reply with *block_message*. Returns the possibly
    modified text plus the list of matched tokens (for auditing).
    """
    if not text or matcher.combined_re is None:
        return ScrubResult(text=text)

    hits: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        hits.append(m.group(0))
        return replacement

    out = matcher.combined_re.sub(_sub, text)

    if hits and mode == "block":
        return ScrubResult(text=block_message, hits=hits, blocked=True)
    return ScrubResult(text=out, hits=hits)


# ---------------------------------------------------------------------------
# Production entry point (config + scrub.json backed, cached by file identity)
# ---------------------------------------------------------------------------

# Cache key is (mtime_ns, size) — nanosecond mtime + size defeats the 1-second
# mtime collision where two edits within the same wall-clock second look equal.
_cache: tuple[tuple[int, int], Matcher, dict] | None = None


def _load() -> tuple[Matcher, dict]:
    """Return (matcher, overrides) built from defaults + a SINGLE read of
    scrub.json, cached by the file's (mtime_ns, size). One read keeps the
    terms/patterns and the mode/replacement overrides mutually consistent."""
    global _cache
    path = scrub_file()
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = (0, 0)
    if _cache is not None and _cache[0] == key:
        return _cache[1], _cache[2]

    terms = default_terms()
    patterns = default_patterns()
    overrides: dict = {}
    if key != (0, 0):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                terms += [str(t) for t in data.get("terms", []) if str(t).strip()]
                patterns += [str(p) for p in data.get("patterns", []) if str(p).strip()]
                overrides = {
                    k: data[k]
                    for k in ("enabled", "mode", "replacement", "block_message")
                    if k in data
                }
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("scrub: could not read {}: {}", path, exc)

    matcher = compile_matcher(terms, patterns)
    _cache = (key, matcher, overrides)
    return matcher, overrides


def scrub_text(text: str) -> ScrubResult:
    """Scrub an outbound reply using the effective (env + scrub.json) config.

    Never raises: a bug in the scrubber must not silently drop replies, but it
    also must not leak — so on unexpected failure it fails CLOSED (returns the
    safe block message). Caught tokens are counted at WARNING and only hashed at
    DEBUG, so the sensitive values themselves never land in the logs.
    """
    try:
        matcher, overrides = _load()
        enabled = bool(overrides.get("enabled", config.SCRUB_ENABLED))
        if not enabled or not text:
            return ScrubResult(text=text)
        mode = str(overrides.get("mode", config.SCRUB_MODE)).strip().lower()
        replacement = str(overrides.get("replacement", config.SCRUB_REPLACEMENT))
        block_message = str(overrides.get("block_message", config.SCRUB_BLOCK_MESSAGE))
        result = scrub(
            text, matcher, mode=mode, replacement=replacement, block_message=block_message
        )
    except Exception as exc:
        logger.error("scrub_text: failing closed after unexpected error: {}", exc)
        return ScrubResult(text=config.SCRUB_BLOCK_MESSAGE, blocked=True)

    if result.hits:
        # Count + mode at WARNING; only HASHED tokens at DEBUG. Never log the raw
        # matched values — a matched private IP / internal hostname would itself
        # leak into the logs, defeating the point of the scrub.
        logger.warning(
            "scrub: caught {} sensitive token(s) in an outbound reply (mode={})",
            len(result.hits),
            mode,
        )
        logger.debug(
            "scrub: caught token hashes: {}",
            sorted({hashlib.sha256(h.lower().encode()).hexdigest()[:8] for h in result.hits}),
        )
    return result
