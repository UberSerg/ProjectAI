"""Write dividend / total-return coverage JSON under .tmp (and as pytest)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.modules.fundamentals.domain.total_return import (
    DividendCashPoint,
    ReturnQuality,
    assess_dividend_coverage,
    compute_gross_total_return,
)


def _repo_root() -> Path:
    # tests/fundamentals → tests → backend → repo (local)
    # In Docker image layout (/app/tests/...), parents[2] is /app — still writable.
    here = Path(__file__).resolve()
    backend_or_app = here.parents[2]
    if (backend_or_app.parent / "docker-compose.yml").exists():
        return backend_or_app.parent
    return backend_or_app


OUT_DIR = _repo_root() / ".tmp" / "daily-autonomy-total-return-v1"
OUT_FILE = OUT_DIR / "dividend-coverage.json"


def _synthetic_live_like_report() -> dict:
    """Mirror live reality without requiring DB: prices exist, dividends empty."""
    report = assess_dividend_coverage(
        instruments_with_price_history=43,
        dividend_events_stored=0,
        instruments_with_dividend_events=0,
        accepted_provider=False,
    )
    fixture = compute_gross_total_return(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        start_price=100.0,
        end_price=90.0,
        dividends=(
            DividendCashPoint(
                ex_date=date(2026, 5, 15),
                amount_per_share=5.0,
                currency="RUB",
            ),
        ),
    )
    payload = report.to_dict()
    payload["fixture_example"] = fixture.to_dict()
    payload["generated_by"] = "tests/fundamentals/test_total_return_coverage_script.py"
    return payload


def write_coverage_report(path: Path | None = None) -> dict:
    out = path or OUT_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = _synthetic_live_like_report()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def test_write_dividend_coverage_json(tmp_path: Path) -> None:
    target = tmp_path / "dividend-coverage.json"
    payload = write_coverage_report(target)
    assert target.is_file()
    assert payload["verdict"] == ReturnQuality.NOT_READY.value
    assert payload["dividend_events_stored"] == 0
    assert payload["fixture_example"]["quality"] == ReturnQuality.READY.value
    assert payload["fixture_example"]["total_return_gross"] == pytest.approx((-10 + 5) / 100)
    # Also materialise the documented project path when the repo root is writable.
    try:
        write_coverage_report(OUT_FILE)
    except OSError:
        pass


if __name__ == "__main__":
    data = write_coverage_report()
    print(json.dumps({"wrote": str(OUT_FILE), "verdict": data["verdict"]}, ensure_ascii=False))
