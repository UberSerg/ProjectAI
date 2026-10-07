"""Focused tests for Intelligence Knowledge Engine (generic principles only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.intelligence.contracts.knowledge import KnowledgeRule
from app.modules.intelligence.knowledge import (
    InMemoryKnowledgeRuleStore,
    KnowledgeEngine,
    PersistOutcome,
    RuleEvaluationContext,
    detect_contradictions,
    evaluate_rule,
    load_pack_file,
    load_packs_from_dir,
)
from app.modules.intelligence.knowledge.evaluator import (
    OBS_DATA_STALE,
    OBS_ISSUER_KIND,
    OBS_MISSING_EVIDENCE_PRESENT,
    OBS_PRICE_MOVE_DIRECTIONAL,
    OBS_UNKNOWN_COERCED_TO_NEUTRAL,
    OBS_USED_INDUSTRIAL_RATIOS,
    OBS_VOLUME_CONFIRMS,
)
from app.modules.intelligence.knowledge.hashutil import content_hash
from app.modules.intelligence.knowledge.ingest import default_knowledge_packs_dir


def test_default_pack_loads_five_methodology_rules() -> None:
    packs = load_packs_from_dir(default_knowledge_packs_dir())
    assert len(packs) >= 1
    pack = next(p for p in packs if p.pack_id == "kraken_methodology_v1")
    assert pack.version == "1"
    assert len(pack.rules) == 5
    ids = {r.rule_id for r in pack.rules}
    assert "momentum_needs_volume_confirmation" in ids
    assert "unknown_not_neutral" in ids
    assert "bank_industrial_ratios_forbidden" in ids


def test_engine_ingest_persist_dedup() -> None:
    engine = KnowledgeEngine(InMemoryKnowledgeRuleStore())
    report = engine.ingest_default_packs()
    assert "kraken_methodology_v1" in report.packs_loaded
    assert report.rule_count == 5
    assert report.inserted == 5
    assert report.conflicts == 0

    again = engine.persist_packs()
    assert all(r.outcome is PersistOutcome.UNCHANGED for r in again)
    assert engine.report_dict()["issues_trades"] is False


def test_version_conflict_on_mutation() -> None:
    store = InMemoryKnowledgeRuleStore()
    rule = KnowledgeRule(
        rule_id="unknown_not_neutral",
        version="1",
        domain="RISK",
        title="Unknown is not neutral",
        principle="Missing must stay UNKNOWN",
    )
    first = store.persist_rule(rule)
    assert first.outcome is PersistOutcome.INSERTED
    mutated = KnowledgeRule(
        rule_id="unknown_not_neutral",
        version="1",
        domain="RISK",
        title="Unknown is not neutral",
        principle="CHANGED PRINCIPLE — must conflict",
    )
    conflict = store.persist_rule(mutated)
    assert conflict.outcome is PersistOutcome.CONFLICT
    assert content_hash(rule) != content_hash(mutated)


def test_markdown_pack_ingestion(tmp_path: Path) -> None:
    md = tmp_path / "notes_pack.md"
    md.write_text(
        """# pack_id: notes_generic_v1
version: "1"
created_from: markdown_notes

## diversification_not_optional
- version: 1
- domain: RISK
- title: Diversification is a risk control
- principle: >
  Concentration without explicit risk acceptance should surface as a risk flag,
  not as a hidden default.
- applicability: portfolio_context
- required_evidence: position_weights
- severity: MEDIUM
- source_reference: generic risk principle
""",
        encoding="utf-8",
    )
    pack = load_pack_file(md)
    assert pack.pack_id == "notes_generic_v1"
    assert len(pack.rules) == 1
    assert pack.rules[0].rule_id == "diversification_not_optional"
    assert "Concentration" in pack.rules[0].principle


def test_trade_actions_rejected_in_pack(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
pack_id: bad
version: "1"
rules:
  - rule_id: do_not_trade
    version: "1"
    domain: RISK
    title: bad
    principle: no
    order: {side: BUY}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not issue trades"):
        load_pack_file(bad)


def test_evaluator_states_for_methodology_rules() -> None:
    engine = KnowledgeEngine()
    engine.ingest_default_packs()
    rules = {r.rule_id: r for r in engine.active_rules()}

    mom = evaluate_rule(
        rules["momentum_needs_volume_confirmation"],
        RuleEvaluationContext(
            active_applicability=frozenset(
                {"technical_model_available", "volume_series_available"}
            ),
            available_evidence=frozenset({"price_return", "volume_relative"}),
            observations={
                OBS_PRICE_MOVE_DIRECTIONAL: True,
                OBS_VOLUME_CONFIRMS: False,
            },
        ),
    )
    assert mom.state == "VIOLATED"

    unk = evaluate_rule(
        rules["unknown_not_neutral"],
        RuleEvaluationContext(
            active_applicability=frozenset({"any_model"}),
            observations={
                OBS_MISSING_EVIDENCE_PRESENT: True,
                OBS_UNKNOWN_COERCED_TO_NEUTRAL: True,
            },
        ),
    )
    assert unk.state == "VIOLATED"

    bank = evaluate_rule(
        rules["bank_industrial_ratios_forbidden"],
        RuleEvaluationContext(
            active_applicability=frozenset({"issuer_kind_bank_fi"}),
            available_evidence=frozenset({"issuer_kind"}),
            observations={
                OBS_ISSUER_KIND: "bank",
                OBS_USED_INDUSTRIAL_RATIOS: True,
            },
        ),
    )
    assert bank.state == "VIOLATED"

    stale = evaluate_rule(
        rules["stale_data_blocks_confidence"],
        RuleEvaluationContext(
            active_applicability=frozenset({"data_freshness_check"}),
            available_evidence=frozenset({"data_freshness"}),
            observations={OBS_DATA_STALE: True},
        ),
    )
    assert stale.state == "TRIGGERED"

    na = evaluate_rule(
        rules["momentum_needs_volume_confirmation"],
        RuleEvaluationContext(active_applicability=frozenset()),
    )
    assert na.state == "NOT_APPLICABLE"


def test_volume_missing_contraindication_is_unknown() -> None:
    engine = KnowledgeEngine()
    engine.ingest_default_packs()
    rule = next(r for r in engine.active_rules() if r.rule_id == "momentum_needs_volume_confirmation")
    ev = evaluate_rule(
        rule,
        RuleEvaluationContext(
            active_applicability=frozenset(
                {"technical_model_available", "volume_series_available"}
            ),
            available_evidence=frozenset({"price_return", "volume_relative"}),
            active_contraindications=frozenset({"missing_volume"}),
            observations={OBS_PRICE_MOVE_DIRECTIONAL: True},
        ),
    )
    assert ev.state == "UNKNOWN"


def test_engine_evaluate_and_contradictions(tmp_path: Path) -> None:
    yaml_path = tmp_path / "claim_pack.yaml"
    yaml_path.write_text(
        """
pack_id: claim_demo_v1
version: "1"
created_from: test
rules:
  - rule_id: claim_requires_volume
    version: "1"
    domain: TECHNICAL
    title: Requires volume
    principle: Volume confirmation is required for momentum claims.
    applicability: [tech]
    claim_key: volume_confirmation
    polarity: requires
    contradicts: [claim_waives_volume]
  - rule_id: claim_waives_volume
    version: "1"
    domain: TECHNICAL
    title: Waives volume
    principle: Volume confirmation may be waived.
    applicability: [tech]
    claim_key: volume_confirmation
    polarity: waives
""",
        encoding="utf-8",
    )
    engine = KnowledgeEngine()
    pack = load_pack_file(yaml_path)
    engine._packs = [pack]
    engine.persist_packs([pack])

    static = detect_contradictions(rules=engine.store.list_active())
    kinds = {c.kind for c in static}
    assert "POLARITY" in kinds
    assert "EXPLICIT" in kinds

    evaluations = engine.evaluate(
        RuleEvaluationContext(
            active_applicability=frozenset({"tech"}),
            observations={
                "triggered_rule_ids": ["claim_requires_volume", "claim_waives_volume"],
            },
        )
    )
    assert {e.state for e in evaluations} == {"TRIGGERED"}
    runtime = engine.contradictions_for(evaluations)
    assert any(c.kind in {"EVAL_EXPLICIT", "EVAL_STATE", "POLARITY", "EXPLICIT"} for c in runtime)


def test_no_books_fabricated_in_report() -> None:
    engine = KnowledgeEngine()
    report = engine.ingest_default_packs()
    assert report.books_pdfs_found == []
    assert report.rule_count == 5
