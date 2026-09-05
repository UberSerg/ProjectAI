"""DB-backed ingest / idempotency / universe protection tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.modules.market_history.application import ingest as ingest_mod
from app.modules.market_history.application.ingest import ingest_file
from app.modules.market_history.application.pipeline import run_audit
from app.modules.market_history.domain import types as domain_types

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external_deep_history"
SAMPLE = FIXTURES / "sample_daily.csv"
TEST_SOURCE_CODE = "EXTERNAL_TEST_SAMPLE_V0"


@pytest.fixture
def external_tables(core_db, monkeypatch):
    """Skip if migration 0016 is not applied. Isolate from live EXTERNAL_30Y source."""
    exists = core_db.execute(
        text("SELECT to_regclass('market.external_sources') IS NOT NULL")
    ).scalar_one()
    if not exists:
        pytest.skip("market.external_* tables missing; apply alembic 20260905_0016")
    monkeypatch.setattr(ingest_mod, "SOURCE_CODE", TEST_SOURCE_CODE)
    monkeypatch.setattr(domain_types, "SOURCE_CODE", TEST_SOURCE_CODE)
    yield core_db


def test_ingest_idempotent_and_never_writes_candles(external_tables) -> None:
    session = external_tables
    candles_before = int(session.execute(text("SELECT count(*) FROM market.candles")).scalar_one())

    first = ingest_file(session, SAMPLE, batch_rows=100)
    assert first.status in {"SUCCESS", "NO_CHANGES"}
    assert first.balances() or first.status == "NO_CHANGES"

    second = ingest_file(session, SAMPLE, batch_rows=100)
    assert second.status == "NO_CHANGES"
    assert second.rows_inserted == 0

    candles_after = int(session.execute(text("SELECT count(*) FROM market.candles")).scalar_one())
    assert candles_after == candles_before


def test_audit_persists_catalog_without_guessing_aliases(external_tables, tmp_path: Path) -> None:
    session = external_tables
    result = run_audit(session, SAMPLE, artifact_dir=tmp_path)
    assert "audit" in result.steps
    rows = session.execute(
        text(
            """
            SELECT source_symbol, match_status, project_symbol
            FROM market.external_source_instruments
            WHERE source_symbol IN ('YNDX', 'TCSG', 'T', 'SBER', 'ZZZZ')
            """
        )
    ).mappings().all()
    by_sym = {r["source_symbol"]: r for r in rows}
    if "YNDX" in by_sym:
        assert by_sym["YNDX"]["project_symbol"] is None
        assert by_sym["YNDX"]["match_status"] == "UNKNOWN_HISTORICAL_SYMBOL"
    if "TCSG" in by_sym:
        assert by_sym["TCSG"]["project_symbol"] is None
    if "T" in by_sym and by_sym["T"]["match_status"] == "EXACT_CURRENT_MATCH":
        assert by_sym["T"]["project_symbol"] == "T"
