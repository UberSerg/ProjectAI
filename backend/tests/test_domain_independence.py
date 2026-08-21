"""Ensure domain layer does not import infrastructure frameworks."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = {
    "fastapi",
    "sqlalchemy",
    "celery",
    "redis",
    "alembic",
    "app.infrastructure",
    "app.api",
    "app.worker",
}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
            found.add(node.module)
    return found


def test_domain_does_not_depend_on_infrastructure() -> None:
    domain_root = Path(__file__).resolve().parents[1] / "app" / "domain"
    violations: list[str] = []
    for path in domain_root.rglob("*.py"):
        imports = _imports_of(path)
        bad = sorted(imports & FORBIDDEN)
        if bad:
            violations.append(f"{path.relative_to(domain_root.parent.parent)}: {bad}")
    assert not violations, "Domain imports forbidden modules:\n" + "\n".join(violations)
