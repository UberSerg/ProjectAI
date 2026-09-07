"""Look-ahead guard: Prediction must not depend on IntradayMarketPort."""

from __future__ import annotations

import ast
from pathlib import Path


def test_prediction_module_does_not_import_intraday() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "modules" / "prediction"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            # Skip unrelated syntax issues (e.g. BOM-only files already handled by utf-8-sig).
            if "intraday" in source.lower() or "IntradayMarketPort" in source:
                offenders.append(str(path))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if "intraday" in mod:
                    offenders.append(f"{path}:{node.lineno}:{mod}")
                for alias in node.names:
                    if "Intraday" in alias.name:
                        offenders.append(f"{path}:{node.lineno}:{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "intraday" in alias.name.lower():
                        offenders.append(f"{path}:{node.lineno}:{alias.name}")
    assert offenders == []


def test_learning_module_does_not_import_intraday() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "modules" / "learning"
    if not root.exists():
        return
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "intraday_market" in text or "IntradayMarketPort" in text:
            offenders.append(str(path))
    assert offenders == []
