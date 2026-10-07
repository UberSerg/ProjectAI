"""Minimal RSS 2.0 / Atom parser (stdlib). Malformed feeds fail soft per-item."""

from __future__ import annotations

import email.utils
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(frozen=True, slots=True)
class FeedItem:
    title: str | None
    link: str | None
    guid: str | None
    published_at: datetime | None
    summary: str | None
    raw_xml_fragment: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    title: str | None
    items: tuple[FeedItem, ...]
    parse_warnings: tuple[str, ...]


def parse_feed(payload: bytes) -> ParsedFeed:
    warnings: list[str] = []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return ParsedFeed(title=None, items=(), parse_warnings=(f"malformed_xml:{exc}",))

    tag = _local(root.tag).lower()
    if tag == "rss" or tag == "rdf":
        return _parse_rss(root, warnings)
    if tag == "feed":
        return _parse_atom(root, warnings)
    warnings.append(f"unknown_root:{tag}")
    # Best-effort: treat as RSS if channel/item present.
    if root.find("channel") is not None:
        return _parse_rss(root, warnings)
    return ParsedFeed(title=None, items=(), parse_warnings=tuple(warnings))


def _parse_rss(root: ET.Element, warnings: list[str]) -> ParsedFeed:
    channel = root.find("channel")
    if channel is None:
        warnings.append("rss_missing_channel")
        return ParsedFeed(title=None, items=(), parse_warnings=tuple(warnings))
    title = _text(channel.find("title"))
    items: list[FeedItem] = []
    for idx, node in enumerate(channel.findall("item")):
        try:
            items.append(_rss_item(node))
        except Exception as exc:  # noqa: BLE001 — isolate bad items
            warnings.append(f"item_{idx}:{type(exc).__name__}:{exc}")
    return ParsedFeed(title=title, items=tuple(items), parse_warnings=tuple(warnings))


def _parse_atom(root: ET.Element, warnings: list[str]) -> ParsedFeed:
    title = _text(root.find("atom:title", _ATOM_NS)) or _text(root.find("title"))
    items: list[FeedItem] = []
    entries = root.findall("atom:entry", _ATOM_NS) or root.findall("entry")
    for idx, node in enumerate(entries):
        try:
            items.append(_atom_entry(node))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"entry_{idx}:{type(exc).__name__}:{exc}")
    return ParsedFeed(title=title, items=tuple(items), parse_warnings=tuple(warnings))


def _rss_item(node: ET.Element) -> FeedItem:
    link = _text(node.find("link"))
    guid = _text(node.find("guid"))
    pub_raw = _text(node.find("pubDate"))
    if pub_raw is None:
        for child in node:
            if _local(child.tag).lower() in {"pubdate", "date", "published"}:
                pub_raw = (child.text or "").strip() or None
                break
    return FeedItem(
        title=_text(node.find("title")),
        link=link,
        guid=guid,
        published_at=parse_rfc822(pub_raw),
        summary=_text(node.find("description")),
        raw_xml_fragment=ET.tostring(node, encoding="unicode"),
    )


def _atom_entry(node: ET.Element) -> FeedItem:
    link = None
    for link_el in node.findall("atom:link", _ATOM_NS) or node.findall("link"):
        rel = link_el.attrib.get("rel", "alternate")
        href = link_el.attrib.get("href")
        if href and rel in {"alternate", ""}:
            link = href
            break
        if href and link is None:
            link = href
    pub_raw = (
        _text(node.find("atom:published", _ATOM_NS))
        or _text(node.find("published"))
        or _text(node.find("atom:updated", _ATOM_NS))
        or _text(node.find("updated"))
    )
    return FeedItem(
        title=_text(node.find("atom:title", _ATOM_NS)) or _text(node.find("title")),
        link=link,
        guid=_text(node.find("atom:id", _ATOM_NS)) or _text(node.find("id")),
        published_at=parse_iso_datetime(pub_raw),
        summary=_text(node.find("atom:summary", _ATOM_NS))
        or _text(node.find("summary"))
        or _text(node.find("atom:content", _ATOM_NS))
        or _text(node.find("content")),
        raw_xml_fragment=ET.tostring(node, encoding="unicode"),
    )


def parse_rfc822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return parse_iso_datetime(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    # MOEX ISS uses "YYYY-MM-DD HH:MM:SS" without TZ — treat as Moscow wall? Prefer naive→UTC
    # only as OBSERVED-relative unknown zone: store as UTC-naive marked? Honest approach:
    # interpret as UTC if Z/offset missing is wrong for MOEX. We use Europe/Moscow offset +03:00
    # only when source documents it; for ISS we attach +03:00 explicitly in the adapter.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag
