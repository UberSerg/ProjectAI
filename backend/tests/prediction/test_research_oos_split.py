"""OOS train contract: no 20d target leakage across the cut."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.modules.prediction.application.research_dataset_loader import split_research_oos

CUT = date(2026, 6, 1)


def _row(
    *,
    as_of: date,
    target: date | None,
    y: float = 0.01,
    valid: bool = True,
    eligible: bool = True,
    sample_id: int = 1,
) -> dict:
    return {
        "sample_id": sample_id,
        "instrument_id": 1,
        "as_of_date": as_of,
        "y": y,
        "target_date_20d": target,
        "label_valid_20d": valid,
        "eligible_20d": eligible,
    }


def test_oos_split_matrix_cut_2026_06_01() -> None:
    frame = pd.DataFrame(
        [
            _row(as_of=date(2026, 5, 1), target=date(2026, 5, 29), sample_id=1),  # A TRAIN
            _row(as_of=date(2026, 5, 20), target=date(2026, 6, 17), sample_id=2),  # B purge
            _row(as_of=date(2026, 6, 1), target=date(2026, 6, 29), sample_id=3),  # C OOS
            _row(as_of=date(2026, 5, 15), target=CUT, sample_id=4),  # target == cut → purge
            _row(as_of=date(2026, 5, 10), target=None, sample_id=5),  # missing target → purge
            _row(as_of=date(2026, 6, 10), target=date(2026, 7, 8), sample_id=6),  # OOS
        ]
    )
    split = split_research_oos(frame, CUT)
    train_ids = set(split["train_df"]["sample_id"].tolist())
    oos_ids = set(split["oos_df"]["sample_id"].tolist())
    assert train_ids == {1}
    assert oos_ids == {3, 6}
    assert split["train_n_before_purge"] == 4  # A,B,cut-eq,null
    assert split["purged_train_boundary_rows"] == 3
    assert split["train_n_after_purge"] == 1
    assert (split["train_df"]["target_date_20d"] < CUT).all()
    assert split["train_df"]["target_date_20d"].notna().all()


def test_oos_split_same_rules_for_v2_v3_v4_shapes() -> None:
    frame = pd.DataFrame(
        [
            _row(as_of=date(2026, 5, 1), target=date(2026, 5, 29), sample_id=10),
            _row(as_of=date(2026, 5, 20), target=date(2026, 6, 17), sample_id=11),
        ]
    )
    a = split_research_oos(frame, CUT)
    b = split_research_oos(frame.copy(), CUT)
    assert a["train_n_after_purge"] == b["train_n_after_purge"] == 1
    assert a["purged_train_boundary_rows"] == b["purged_train_boundary_rows"] == 1
