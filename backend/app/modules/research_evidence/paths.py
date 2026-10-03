"""Filesystem layout for Research Evidence Engine V1 artifacts (not git)."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings


def research_evidence_root(root: Path | None = None) -> Path:
    base = root or Path(get_settings().models_data_path)
    return base / "research_evidence"


def experiment_dir(fingerprint: str, *, root: Path | None = None) -> Path:
    return research_evidence_root(root) / fingerprint


def campaign_runtime_dir(workflow_id: int | str, *, root: Path | None = None) -> Path:
    return research_evidence_root(root) / "campaign_runtime" / str(workflow_id)


def campaigns_root(*, root: Path | None = None) -> Path:
    return research_evidence_root(root) / "campaigns"


def list_campaign_dirs(*, root: Path | None = None) -> list[Path]:
    base = campaigns_root(root=root)
    if not base.exists():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs


def list_experiment_dirs(*, root: Path | None = None) -> list[Path]:
    base = research_evidence_root(root)
    if not base.exists():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir() and (p / "evidence_overview.json").exists()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs


def find_experiment_dir(experiment_id: str, *, root: Path | None = None) -> Path | None:
    """Resolve an experiment directory by fingerprint / folder name via manifest.json."""
    if not experiment_id:
        return None
    direct = experiment_dir(experiment_id, root=root)
    if (direct / "manifest.json").is_file():
        return direct
    base = research_evidence_root(root)
    if not base.exists():
        return None
    matches: list[Path] = []
    for path in base.iterdir():
        manifest_path = path / "manifest.json"
        if not path.is_dir() or not manifest_path.is_file():
            continue
        if path.name == experiment_id or path.name.startswith(experiment_id):
            matches.append(path)
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fingerprint = data.get("experiment_fingerprint") if isinstance(data, dict) else None
        if fingerprint == experiment_id:
            matches.append(path)
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
