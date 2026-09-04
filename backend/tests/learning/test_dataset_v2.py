"""Dataset PIT V2 — pins, mechanical labels, V1 immutability."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.learning.models import DatasetSpec
from app.modules.learning.application.labels import ForwardReturnLabelCalculator, PriceObservation
from app.modules.learning.application.seed import seed_dataset_specs
from app.modules.learning.dataset_config import (
    PIT_DAILY_CORE_CODE,
    PIT_DAILY_CORE_V2,
    PIT_DAILY_CORE_V2_VERSION,
    feature_names_from_manifest,
    label_names_from_manifest,
    uses_mechanical_label_basis,
)
from app.modules.market.application.mechanical_adjustment import MechanicalAction


def test_v2_spec_exact_pins(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    v2 = core_db.scalar(
        select(DatasetSpec).where(
            DatasetSpec.code == PIT_DAILY_CORE_CODE,
            DatasetSpec.version == PIT_DAILY_CORE_V2_VERSION,
        )
    )
    assert v2 is not None
    assert v2.is_active is False
    assert v2.basic_feature_set_code == "basic_daily"
    assert v2.basic_feature_set_version == 2
    assert v2.technical_feature_set_code == "technical_daily"
    assert v2.technical_feature_set_version == 2
    assert v2.technical_model_code == "rules"
    assert v2.technical_model_version == 2
    assert v2.relation_set_code == "basic_relations"
    assert v2.relation_set_version == 2
    assert uses_mechanical_label_basis(v2.label_spec)
    assert v2.label_spec.get("dividend_adjusted") is False
    assert v2.label_spec.get("total_return") is False


def test_v1_remains_active_and_raw_pinned(core_db: Session) -> None:
    seed_dataset_specs(core_db)
    active = core_db.scalar(select(DatasetSpec).where(DatasetSpec.is_active.is_(True)))
    assert active is not None
    assert active.code == PIT_DAILY_CORE_CODE
    assert active.version == 1
    assert active.basic_feature_set_version == 1
    assert active.technical_feature_set_version == 1
    assert active.technical_model_version == 1
    assert active.relation_set_version == 1
    assert not uses_mechanical_label_basis(active.label_spec)


def test_v2_x_schema_matches_v1_feature_names() -> None:
    v1_features = feature_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    assert len(v1_features) == 90
    assert "forward_return_5d" not in v1_features
    assert "return_5d" in v1_features
    assert "rel_imoex_w60_pearson" in v1_features
    labels = label_names_from_manifest(PIT_DAILY_CORE_V2["feature_manifest"])
    assert labels == [
        "forward_return_1d",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
    ]


def test_vtbr_style_reverse_split_label() -> None:
    # Reverse 5000→1: factor=1/5000. Raw would look like ×5000 jump.
    obs = [
        PriceObservation(date(2024, 7, 12), 0.02, 1),
        PriceObservation(date(2024, 7, 15), 95.0, 2),
    ]
    actions = [
        MechanicalAction(
            instrument_id=1,
            event_date=date(2024, 7, 15),
            event_type="REVERSE_SPLIT",
            factor=Decimal("1") / Decimal("5000"),
        )
    ]
    raw = ForwardReturnLabelCalculator([1]).calculate(
        obs, as_of=date(2024, 7, 12), discontinuity_dates={date(2024, 7, 15)}
    )
    assert raw.label_valid["1d"] is False

    mech = ForwardReturnLabelCalculator([1]).calculate(
        obs,
        as_of=date(2024, 7, 12),
        discontinuity_dates={date(2024, 7, 15)},
        mechanical_actions=actions,
        price_basis="mechanical_adjusted",
    )
    # comparable: 0.02 / (1/5000) = 100; target 95 → -5%
    assert mech.label_valid["1d"] is True
    assert abs(mech.labels.forward_return_1d - (95.0 / 100.0 - 1.0)) < 1e-9


def test_no_ca_mechanical_equals_raw() -> None:
    obs = [
        PriceObservation(date(2024, 1, 2), 200.0, 1),
        PriceObservation(date(2024, 1, 3), 210.0, 2),
        PriceObservation(date(2024, 1, 4), 220.0, 3),
        PriceObservation(date(2024, 1, 5), 230.0, 4),
        PriceObservation(date(2024, 1, 8), 240.0, 5),
        PriceObservation(date(2024, 1, 9), 250.0, 6),
    ]
    raw = ForwardReturnLabelCalculator([5]).calculate(obs, as_of=date(2024, 1, 2))
    mech = ForwardReturnLabelCalculator([5]).calculate(
        obs, as_of=date(2024, 1, 2), price_basis="mechanical_adjusted", mechanical_actions=[]
    )
    assert raw.labels.forward_return_5d == mech.labels.forward_return_5d
    assert abs(raw.labels.forward_return_5d - (250.0 / 200.0 - 1.0)) < 1e-12
