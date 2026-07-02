"""Tests for the output-side confidentiality scrub."""

from __future__ import annotations

import json

from wisdom_channel import config
from wisdom_channel import scrub as scrub_mod
from wisdom_channel.scrub import (
    ScrubResult,
    compile_matcher,
    default_patterns,
    default_terms,
    scrub,
    scrub_text,
)

MATCHER = compile_matcher(default_terms(), default_patterns())


def _run(text: str, **kw) -> ScrubResult:
    return scrub(text, MATCHER, **kw)


# ---------------------------------------------------------------------------
# Redaction of provider aliases
# ---------------------------------------------------------------------------


def test_redacts_provider_alias():
    r = _run("这个功能其实是用 openaihk 提供的")
    assert "openaihk" not in r.text
    assert "我们的服务" in r.text
    assert r.hits == ["openaihk"]
    assert r.blocked is False


def test_case_insensitive():
    r = _run("底层是 OpenAIHK 和 TTAPI")
    assert "OpenAIHK" not in r.text
    assert "TTAPI" not in r.text
    assert len(r.hits) == 2


def test_hyphenated_alias_matches_whole():
    r = _run("走的是 openai-hk 通道")
    assert "openai-hk" not in r.text
    assert r.hits == ["openai-hk"]


def test_word_boundary_no_partial_match():
    # 'ttapi' embedded in a larger word must NOT be redacted.
    r = _run("this is a chatttapixx token")
    assert r.text == "this is a chatttapixx token"
    assert r.hits == []


# ---------------------------------------------------------------------------
# Infra patterns
# ---------------------------------------------------------------------------


def test_private_ip_redacted_public_kept():
    r = _run("内网 10.1.2.3 而公网 1.2.3.4")
    assert "10.1.2.3" not in r.text
    assert "1.2.3.4" in r.text  # public IP untouched
    assert r.hits == ["10.1.2.3"]


def test_internal_image_redacted():
    r = _run("镜像是 ghcr.io/acedatacloud/platform-backend:latest 部署的")
    assert "ghcr.io/acedatacloud" not in r.text
    assert r.hits


def test_k8s_service_dns_redacted():
    r = _run("连的是 platform-service-localization.svc.cluster.local")
    assert "svc.cluster.local" not in r.text
    assert r.hits


def test_tencent_resource_id_redacted():
    r = _run("实例 ins-f8mcnsrt 上跑的")
    assert "ins-f8mcnsrt" not in r.text
    assert r.hits == ["ins-f8mcnsrt"]


# ---------------------------------------------------------------------------
# No false positives on legitimate customer-facing text
# ---------------------------------------------------------------------------


def test_brand_name_not_redacted():
    text = "AceDataCloud 为你提供最好的 AI 服务，我们的服务很稳定"
    r = _run(text)
    assert r.text == text
    assert r.hits == []


def test_clean_text_unchanged():
    text = "你好，请问有什么可以帮你的？"
    r = _run(text)
    assert r.text == text
    assert r.hits == []


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_block_mode_replaces_whole_reply():
    r = _run("我们用了 ttapi", mode="block", block_message="不便回答")
    assert r.text == "不便回答"
    assert r.blocked is True
    assert r.hits == ["ttapi"]


def test_block_mode_no_hit_passes_through():
    r = _run("正常内容", mode="block", block_message="不便回答")
    assert r.text == "正常内容"
    assert r.blocked is False


def test_custom_replacement():
    r = _run("由 piapi 驱动", replacement="[已隐藏]")
    assert "[已隐藏]" in r.text
    assert "piapi" not in r.text


# ---------------------------------------------------------------------------
# compile_matcher robustness
# ---------------------------------------------------------------------------


def test_invalid_pattern_skipped_not_raised():
    m = compile_matcher(["foo"], ["(unclosed", r"\bbar\b"])
    r = scrub("foo and bar", m)
    assert "foo" not in r.text
    assert "bar" not in r.text


def test_empty_matcher_is_noop():
    m = compile_matcher([], [])
    r = scrub("anything at all", m)
    assert r.text == "anything at all"
    assert r.hits == []


def test_replacement_not_reprocessed_single_pass():
    # Single left-to-right pass: a replacement that itself looks like another
    # denylisted token must NOT be re-matched (no double substitution).
    m = compile_matcher(["foo"], ["BAR"])
    r = scrub("foo", m, replacement="BAR")
    assert r.text == "BAR"
    assert r.hits == ["foo"]  # exactly one hit, the injected 'BAR' is left alone


# ---------------------------------------------------------------------------
# scrub_text (config + scrub.json backed)
# ---------------------------------------------------------------------------


def test_scrub_text_disabled(monkeypatch):
    monkeypatch.setattr(config, "SCRUB_ENABLED", False)
    r = scrub_text("我们用了 openaihk")
    assert r.text == "我们用了 openaihk"
    assert r.hits == []


def test_scrub_text_fails_closed_on_error(monkeypatch):
    # A bug in the scrubber must not leak (fail-open) or crash the send — it
    # fails CLOSED to the safe block message.
    monkeypatch.setattr(config, "SCRUB_BLOCK_MESSAGE", "SAFE-FALLBACK")

    def _boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scrub_mod, "_load", _boom)
    r = scrub_text("底层是 openaihk 千万别泄漏")
    assert r.text == "SAFE-FALLBACK"
    assert r.blocked is True
    assert "openaihk" not in r.text


def test_scrub_text_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCRUB_ENABLED", True)
    monkeypatch.setattr(config, "SCRUB_MODE", "redact")
    monkeypatch.setenv("WECHAT_STATE_DIR", str(tmp_path))
    scrub_mod._cache = None
    r = scrub_text("底层是 openaihk")
    assert "openaihk" not in r.text
    assert r.hits == ["openaihk"]


def test_scrub_json_extends_terms(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCRUB_ENABLED", True)
    monkeypatch.setattr(config, "SCRUB_MODE", "redact")
    monkeypatch.setenv("WECHAT_STATE_DIR", str(tmp_path))
    (tmp_path / "scrub.json").write_text(
        json.dumps({"terms": ["supersecretvendor"]}), encoding="utf-8"
    )
    scrub_mod._cache = None
    r = scrub_text("powered by supersecretvendor")
    assert "supersecretvendor" not in r.text
    assert r.hits == ["supersecretvendor"]


def test_scrub_json_block_mode_override(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCRUB_ENABLED", True)
    monkeypatch.setenv("WECHAT_STATE_DIR", str(tmp_path))
    (tmp_path / "scrub.json").write_text(
        json.dumps({"mode": "block", "block_message": "NO"}), encoding="utf-8"
    )
    scrub_mod._cache = None
    r = scrub_text("uses ttapi")
    assert r.text == "NO"
    assert r.blocked is True
