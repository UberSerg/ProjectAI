"""Additional enrichment queue / resume / dataset-guard tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.modules.investment.application.enrichment_service import (
    claim_enrichment_batch,
    enqueue_enrichment,
)
from app.modules.investment.domain.enrichment import (
    EnrichmentKind,
    EnrichmentPriority,
    EnrichmentStatus,
)


def test_enqueue_creates_pending_job() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    added = []
    session.add.side_effect = lambda obj: added.append(obj)
    job = enqueue_enrichment(
        session, 5, EnrichmentKind.FIXED_INCOME_CASHFLOWS, EnrichmentPriority.P2_OFZ
    )
    assert job.instrument_id == 5
    assert job.kind == EnrichmentKind.FIXED_INCOME_CASHFLOWS.value
    assert job.priority == int(EnrichmentPriority.P2_OFZ)
    assert job.status == EnrichmentStatus.PENDING.value
    assert added


def test_claim_batch_marks_running() -> None:
    job = MagicMock()
    job.status = EnrichmentStatus.PENDING.value
    job.attempts = 0
    session = MagicMock()
    session.scalars.return_value = [job]
    claimed = claim_enrichment_batch(session, batch_size=10)
    assert claimed == [job]
    assert job.status == EnrichmentStatus.RUNNING.value
    assert job.attempts == 1


def test_run_batch_disabled_when_flag_off() -> None:
    from app.modules.investment.application import enrichment_service as svc

    with patch.object(svc, "get_settings") as gs:
        gs.return_value.fi_enrichment_enabled = False
        result = svc.run_fi_enrichment_batch(MagicMock())
    assert result["status"] == "DISABLED"


def test_dataset_v2_pin_untouched_by_enrichment_module() -> None:
    """Guard: enrichment module must not import dataset builders."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "app/modules/investment/application/enrichment_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = [i for i in imports if "dataset" in i.lower() or "feature_set" in i.lower()]
    assert forbidden == []
