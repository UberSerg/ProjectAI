"""Filesystem layout for Research Evidence Engine V1 artifacts (not git)."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def research_evidence_root(root: Path | None = None) -> Path:
    base = root or Path(get_settings().models_data_path)
    return base / "research_evidence"


def experiment_dir(fingerprint: str, *, root: Path | None = None) -> Path:
    return research_evidence_root(root) / fingerprint


def list_experiment_dirs(*, root: Path | None = None) -> list[Path]:
    base = research_evidence_root(root)
    if not base.exists():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir() and (p / "evidence_overview.json").exists()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs
