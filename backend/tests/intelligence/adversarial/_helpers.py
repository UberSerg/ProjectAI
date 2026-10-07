"""Shared adversarial oracles — encode security/PIT expectations for stubs + modules."""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.modules.intelligence.contracts.provenance import EvidenceRef, known_at_allows
from app.modules.intelligence.contracts.snapshots_domain import SourceDocumentV1

INTELLIGENCE_ROOT = (
    Path(__file__).resolve().parents[3] / "app" / "modules" / "intelligence"
)

# Private / link-local / metadata targets that an RSS fetcher must never open.
_BLOCKED_HOST_LITERALS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
    }
)

_FORBIDDEN_INTEL_IMPORT_PREFIXES = (
    "app.modules.portfolio.application.broker",
    "app.modules.portfolio.application.personal_operations",
    "app.modules.shadow.application.service",
    "app.modules.decision.application.daily_decision",
    "app.infrastructure.broker",
)

_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "create_personal_operation",
        "execute_order",
        "place_order",
        "promote_candidate",
        "switch_shadow_policy",
        "activate_dataset_spec",
        "set_active_dataset_version",
    }
)


def to_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def honest_known_at(
    *,
    source_published_at: date | datetime | None,
    observed_at: date | datetime | None,
) -> date | None:
    """Conservative decision-availability: max(published, observed); missing either → None.

    Backdated RSS (published << observed) must not become known before observation.
    Fabricating known_at from period_end / effective_at is forbidden.
    """
    if source_published_at is None or observed_at is None:
        return None
    return max(to_date(source_published_at), to_date(observed_at))


def pit_visible_docs(
    docs: Iterable[SourceDocumentV1],
    *,
    as_of: date | datetime,
) -> list[SourceDocumentV1]:
    return [d for d in docs if known_at_allows(as_of, d.known_at)]


def pit_visible_evidence(
    refs: Iterable[EvidenceRef],
    *,
    as_of: date | datetime,
) -> list[EvidenceRef]:
    return [r for r in refs if known_at_allows(as_of, r.known_at)]


def content_hash(payload: str | bytes) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def is_ssrf_blocked_url(url: str) -> bool:
    """Return True when URL must be rejected by intelligence news fetch (SSRF oracle)."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return True
    if parsed.scheme not in {"http", "https"}:
        return True
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return True
    if host in _BLOCKED_HOST_LITERALS:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    # Bare IPv4 / IPv6 literals
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    except ValueError:
        pass
    # Decimal / hex / octal IP tricks commonly used in SSRF bypasses
    if re.fullmatch(r"\d+", host) or re.fullmatch(r"0x[0-9a-f]+", host):
        return True
    return False


def assert_rss_url_allowed_or_raise(url: str, *, allowlist: frozenset[str]) -> None:
    """Contract expected of Agent D source registry: allowlist + SSRF gate."""
    if is_ssrf_blocked_url(url):
        raise ValueError(f"SSRF_BLOCKED: {url}")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in allowlist:
        raise ValueError(f"RSS_URL_NOT_ALLOWLISTED: {host}")


def scan_intelligence_for_forbidden_production_mutations() -> list[str]:
    """Static red-team scan: intelligence package must not call production mutators."""
    findings: list[str] = []
    if not INTELLIGENCE_ROOT.is_dir():
        return ["intelligence root missing"]
    for path in INTELLIGENCE_ROOT.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(f"{path}: syntax error {exc}")
            continue
        rel = path.relative_to(INTELLIGENCE_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in _FORBIDDEN_INTEL_IMPORT_PREFIXES:
                    if node.module == prefix or node.module.startswith(prefix + "."):
                        findings.append(f"{rel}: forbidden import {node.module}")
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in _FORBIDDEN_CALL_NAMES:
                    findings.append(f"{rel}: forbidden call {name}")
    return findings


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def isolation_flags_must_be_false(report: dict[str, Any]) -> None:
    for key in (
        "persist_registry",
        "candidate_promotion",
        "shadow_policy_switch",
        "daily_decision_switch",
        "broker_execution",
    ):
        assert report.get(key) is False, f"{key} must be False, got {report.get(key)!r}"
