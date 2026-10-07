"""Models must not import sibling adapters (independence invariant)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SIGNALS_DIR = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "modules"
    / "intelligence"
    / "signals"
)

MODEL_MODULES = {
    "technical",
    "fundamental",
    "event",
    "macro",
    "cross_sectional_ml",
    "intraday",
}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


@pytest.mark.parametrize("module_name", sorted(MODEL_MODULES))
def test_model_does_not_import_sibling_models(module_name: str) -> None:
    path = SIGNALS_DIR / f"{module_name}.py"
    assert path.is_file()
    imports = _imports_of(path)
    siblings = MODEL_MODULES - {module_name}
    forbidden = {
        f"app.modules.intelligence.signals.{sib}"
        for sib in siblings
    } | {f"app.modules.intelligence.signals.{sib}" for sib in siblings}
    # Also catch relative sibling imports like `.technical`
    relative_hits = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            if node.module in siblings:
                relative_hits.append(node.module)
        if isinstance(node, ast.ImportFrom) and node.level and node.names:
            for alias in node.names:
                if alias.name in {
                    "TechnicalModelV1",
                    "FundamentalModelV1",
                    "EventModelV1",
                    "MacroModelV1",
                    "CrossSectionalMLModelV1",
                    "IntradayStructureModelV1",
                } and module_name != {
                    "TechnicalModelV1": "technical",
                    "FundamentalModelV1": "fundamental",
                    "EventModelV1": "event",
                    "MacroModelV1": "macro",
                    "CrossSectionalMLModelV1": "cross_sectional_ml",
                    "IntradayStructureModelV1": "intraday",
                }.get(alias.name):
                    relative_hits.append(alias.name)

    assert not (imports & forbidden), f"{module_name} imports siblings: {imports & forbidden}"
    assert not relative_hits, f"{module_name} relative sibling imports: {relative_hits}"


def test_package_exports_all_models() -> None:
    from app.modules.intelligence import signals

    for name in (
        "TechnicalModelV1",
        "FundamentalModelV1",
        "EventModelV1",
        "MacroModelV1",
        "CrossSectionalMLModelV1",
        "IntradayStructureModelV1",
    ):
        assert hasattr(signals, name)
