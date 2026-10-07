"""Markdown / YAML knowledge-pack ingestion (no fabricated literature excerpts)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.modules.intelligence.contracts.knowledge import KnowledgeRule
from app.modules.intelligence.knowledge.pack import KnowledgePack

_TRADE_ACTION_KEYS = frozenset(
    {
        "order",
        "side",
        "buy",
        "sell",
        "trade",
        "execution",
        "broker_order",
        "order_intent",
    }
)

_MD_PACK_HEADER = re.compile(
    r"^#\s*pack_id\s*:\s*(?P<pack_id>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_MD_RULE_HEADER = re.compile(r"^##\s+(?P<rule_id>[a-zA-Z0-9_.:-]+)\s*$", re.MULTILINE)


def default_knowledge_packs_dir() -> Path:
    """Repo-relative packs directory (works from backend/ or repo root cwd)."""
    here = Path(__file__).resolve()
    # .../backend/app/modules/intelligence/knowledge/ingest.py → repo root
    repo_root = here.parents[5]
    return repo_root / "docs" / "intelligence" / "knowledge_packs"


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return tuple(p for p in parts if p)
    if isinstance(value, list | tuple):
        return tuple(str(x) for x in value)
    raise ValueError(f"expected list/str for multi-value field, got {type(value)!r}")


def _reject_trade_actions(payload: dict[str, Any], *, where: str) -> None:
    lowered = {str(k).lower() for k in payload}
    bad = lowered & _TRADE_ACTION_KEYS
    if bad:
        raise ValueError(f"knowledge rules must not issue trades ({where}): {sorted(bad)}")


def _rule_from_mapping(
    raw: dict[str, Any],
    *,
    default_created_from: str,
    default_source_location: str | None,
) -> tuple[KnowledgeRule, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("rule entry must be a mapping")
    _reject_trade_actions(raw, where=str(raw.get("rule_id", "<unknown>")))

    rule_id = str(raw["rule_id"]).strip()
    version = str(raw.get("version", "1")).strip()
    domain = str(raw["domain"]).strip()
    title = str(raw["title"]).strip()
    principle = str(raw["principle"]).strip()
    if not rule_id or not domain or not title or not principle:
        raise ValueError("rule_id, domain, title, principle are required")

    body = dict(raw.get("body") or {})
    if not isinstance(body, dict):
        raise ValueError(f"rule {rule_id}: body must be a mapping")
    for key in ("claim_key", "polarity", "contradicts"):
        if key in raw and key not in body:
            body[key] = raw[key]

    rule = KnowledgeRule(
        rule_id=rule_id,
        version=version,
        domain=domain,
        title=title,
        principle=principle,
        applicability=_as_tuple(raw.get("applicability")),
        required_evidence=_as_tuple(raw.get("required_evidence")),
        contraindications=_as_tuple(raw.get("contraindications")),
        severity=str(raw.get("severity", "MEDIUM")),
        source_reference=(
            str(raw["source_reference"]) if raw.get("source_reference") is not None else None
        ),
        source_location=(
            str(raw["source_location"])
            if raw.get("source_location") is not None
            else default_source_location
        ),
        created_from=str(raw.get("created_from") or default_created_from),
        status=str(raw.get("status") or "ACTIVE"),
    )
    return rule, body


def _pack_from_mapping(data: dict[str, Any], *, source_path: str | None) -> KnowledgePack:
    if not isinstance(data, dict):
        raise ValueError("pack root must be a mapping")
    pack_id = str(data.get("pack_id") or "").strip()
    if not pack_id:
        raise ValueError("pack_id is required")
    version = str(data.get("version", "1")).strip()
    created_from = str(data.get("created_from") or "kraken_methodology")
    rules_raw = data.get("rules") or []
    if not isinstance(rules_raw, list):
        raise ValueError("rules must be a list")

    rules: list[KnowledgeRule] = []
    bodies: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    for entry in rules_raw:
        rule, body = _rule_from_mapping(
            entry,
            default_created_from=created_from,
            default_source_location=source_path,
        )
        key = (rule.rule_id, rule.version)
        if key in seen:
            raise ValueError(f"duplicate rule in pack {pack_id}: {rule.rule_id}@{rule.version}")
        seen.add(key)
        rules.append(rule)
        if body:
            bodies[rule.rule_id] = body

    return KnowledgePack(
        pack_id=pack_id,
        version=version,
        created_from=created_from,
        rules=tuple(rules),
        source_path=source_path,
        rule_bodies=bodies,
    )


def load_yaml_pack(path: Path) -> KnowledgePack:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError(f"empty YAML pack: {path}")
    return _pack_from_mapping(data, source_path=str(path.as_posix()))


def _parse_md_scalar_block(block: str) -> dict[str, Any]:
    """Parse a simple markdown rule block of `- key: value` / `key: value` lines."""
    out: dict[str, Any] = {}
    principle_lines: list[str] = []
    in_principle = False
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_principle:
                principle_lines.append("")
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if in_principle and not re.match(r"^[a-zA-Z_][\w]*\s*:", stripped):
            principle_lines.append(stripped)
            continue
        m = re.match(r"^([a-zA-Z_][\w]*)\s*:\s*(.*)$", stripped)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key == "principle":
            in_principle = True
            if value:
                principle_lines = [value]
            else:
                principle_lines = []
            continue
        in_principle = False
        if principle_lines:
            out["principle"] = " ".join(p for p in principle_lines if p).strip()
            principle_lines = []
        out[key] = value
    if principle_lines:
        out["principle"] = " ".join(p for p in principle_lines if p).strip()
    return out


def load_markdown_pack(path: Path) -> KnowledgePack:
    text = path.read_text(encoding="utf-8")
    header = _MD_PACK_HEADER.search(text)
    if not header:
        raise ValueError(f"markdown pack missing `# pack_id: ...` header: {path}")
    pack_id = header.group("pack_id")

    meta: dict[str, Any] = {"pack_id": pack_id, "version": "1", "created_from": "markdown_notes"}
    # Capture pack-level key: value lines before first ## rule
    first_rule = _MD_RULE_HEADER.search(text)
    preamble = text[header.end() : first_rule.start() if first_rule else len(text)]
    for line in preamble.splitlines():
        m = re.match(r"^([a-zA-Z_][\w]*)\s*:\s*(.+)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()

    rules_raw: list[dict[str, Any]] = []
    matches = list(_MD_RULE_HEADER.finditer(text))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _parse_md_scalar_block(text[start:end])
        block["rule_id"] = match.group("rule_id")
        rules_raw.append(block)

    meta["rules"] = rules_raw
    return _pack_from_mapping(meta, source_path=str(path.as_posix()))


def load_pack_file(path: Path | str) -> KnowledgePack:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return load_yaml_pack(p)
    if suffix == ".md":
        return load_markdown_pack(p)
    raise ValueError(f"unsupported knowledge pack format: {p.suffix}")


def load_packs_from_dir(directory: Path | str | None = None) -> list[KnowledgePack]:
    root = Path(directory) if directory is not None else default_knowledge_packs_dir()
    if not root.is_dir():
        return []
    packs: list[KnowledgePack] = []
    for path in sorted(root.iterdir()):
        if path.suffix.lower() in {".yaml", ".yml", ".md"} and path.is_file():
            packs.append(load_pack_file(path))
    return packs


def ingest_path(path: Path | str) -> list[KnowledgePack]:
    """Load a single file or all packs under a directory."""
    p = Path(path)
    if p.is_dir():
        return load_packs_from_dir(p)
    return [load_pack_file(p)]
