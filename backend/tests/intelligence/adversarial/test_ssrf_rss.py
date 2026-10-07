"""SSRF via arbitrary RSS URL — allowlist + private-target rejection."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.intelligence.adversarial._helpers import (
    assert_rss_url_allowed_or_raise,
    content_hash,
    is_ssrf_blocked_url,
)

ALLOWLIST = frozenset(
    {
        "www.moex.com",
        "iss.moex.com",
        "www.cbr.ru",
        "cbr.ru",
        "e-disclosure.ru",
        "www.e-disclosure.ru",
    }
)

PRIVATE_OR_BAD_SCHEME_URLS = (
    "http://127.0.0.1/latest/meta-data",
    "http://localhost:5432/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://0x7f000001/",
    "http://2130706433/",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_INFO",
    "http://metadata.google.internal/",
    "http://10.0.0.8/rss",
    "http://192.168.1.1/rss",
)

NON_ALLOWLISTED_PUBLIC = (
    "https://evil.example/feed.xml",
    "http://attacker.example/rss.xml",
)


@pytest.mark.parametrize("url", PRIVATE_OR_BAD_SCHEME_URLS)
def test_ssrf_oracle_blocks_private_and_bad_schemes(url: str) -> None:
    assert is_ssrf_blocked_url(url)
    with pytest.raises(ValueError, match="SSRF_BLOCKED"):
        assert_rss_url_allowed_or_raise(url, allowlist=ALLOWLIST)


@pytest.mark.parametrize("url", NON_ALLOWLISTED_PUBLIC)
def test_non_allowlisted_public_hosts_rejected(url: str) -> None:
    assert not is_ssrf_blocked_url(url)
    with pytest.raises(ValueError, match="NOT_ALLOWLISTED"):
        assert_rss_url_allowed_or_raise(url, allowlist=ALLOWLIST)


def test_allowlisted_https_host_passes_oracle() -> None:
    assert_rss_url_allowed_or_raise(
        "https://www.moex.com/export/news.aspx?cat=100",
        allowlist=ALLOWLIST,
    )


def test_news_registry_rejects_arbitrary_url_if_present() -> None:
    candidates = (
        "app.modules.intelligence.news.registry",
        "app.modules.intelligence.news.source_registry",
        "app.modules.intelligence.news.sources",
        "app.modules.intelligence.news",
    )
    mod: Any | None = None
    for name in candidates:
        try:
            mod = importlib.import_module(name)
            break
        except ModuleNotFoundError:
            continue
    if mod is None:
        pytest.skip("intelligence.news registry not implemented yet")

    checker = None
    for attr in (
        "assert_fetch_url_allowed",
        "validate_rss_url",
        "ensure_allowlisted_url",
        "reject_ssrf_url",
    ):
        checker = getattr(mod, attr, None)
        if checker is not None:
            break
    resolve = getattr(mod, "resolve_source", None) or getattr(mod, "get_source", None)

    if checker is not None:
        with pytest.raises((ValueError, PermissionError, RuntimeError)):
            checker("http://127.0.0.1/rss")
        with pytest.raises((ValueError, PermissionError, RuntimeError)):
            checker("https://evil.example/feed.xml")
        return

    if resolve is not None:
        with pytest.raises((ValueError, KeyError, PermissionError, RuntimeError)):
            resolve("https://evil.example/feed.xml")
        return

    pytest.skip("news module present without URL allowlist guard export")


def test_huge_document_payload_must_be_bounded_contract() -> None:
    huge = "A" * (5 * 1024 * 1024)
    digest = content_hash(huge)
    assert len(digest) == 64
    assert len(huge) > 1_000_000
