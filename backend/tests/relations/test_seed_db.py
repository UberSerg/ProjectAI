"""DB integration for relation sets / inputs seed."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.analytics.relation_models import RelationInput, RelationSet
from app.infrastructure.market.models import Instrument, Series
from app.modules.market.application.seed import seed_market_universe
from app.modules.relations.application.resolve import RelationSetResolveError, resolve_relation_set
from app.modules.relations.application.seed import seed_relation_inputs, seed_relation_sets


def test_seed_relation_sets(core_db: Session) -> None:
    result = seed_relation_sets(core_db)
    assert result["ensured"] >= 2
    active = core_db.scalar(select(RelationSet).where(RelationSet.is_active.is_(True)))
    assert active is not None
    assert active.code == "basic_relations"
    assert active.version == 1
    v2 = core_db.scalar(select(RelationSet).where(RelationSet.code == "basic_relations", RelationSet.version == 2))
    assert v2 is not None and v2.is_active is False
    assert "windows" in active.parameters
    assert active.parameters["minimum_coverage_ratio"] == 0.8


def test_resolve_relation_set(core_db: Session) -> None:
    seed_relation_sets(core_db)
    row = resolve_relation_set(core_db, "basic_relations")
    assert row.version == 1
    exact = resolve_relation_set(core_db, "basic_relations", 1)
    assert exact.id == row.id
    with pytest.raises(RelationSetResolveError) as exc:
        resolve_relation_set(core_db, "missing")
    assert exc.value.status_code == 404


def test_seed_relation_inputs(core_db: Session) -> None:
    seed_market_universe(core_db)
    seed_relation_sets(core_db)
    result = seed_relation_inputs(core_db)
    assert result["instruments"] > 0
    assert result["series"] >= 3
    inputs = list(core_db.scalars(select(RelationInput).where(RelationInput.is_active.is_(True))))
    codes = {i.code for i in inputs}
    assert any(c.startswith("instrument:SBER:log_return_1d") for c in codes)
    assert any(c.startswith("series:USD_RUB_CBR:pct_change") for c in codes)
    assert any(c.startswith("series:KEY_RATE:absolute_change") for c in codes)
    # FK is to relation_inputs subjects, not instruments table — subject_ids must exist
    inst_ids = {i.id for i in core_db.scalars(select(Instrument))}
    series_ids = {s.id for s in core_db.scalars(select(Series))}
    for inp in inputs:
        if inp.subject_type == "instrument":
            assert inp.subject_id in inst_ids
        else:
            assert inp.subject_id in series_ids
