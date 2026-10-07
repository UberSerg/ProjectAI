"""Feature pack contract tests for Intelligence Research V1."""

from __future__ import annotations

from app.modules.intelligence.research.constants import FEATURE_PACKS, PACK_INTELLIGENCE_FULL
from app.modules.intelligence.research.packs import (
    NEWS_FEATURE_NAMES,
    all_feature_packs,
    base_feature_names,
    build_feature_pack,
    feature_group_definitions,
    prospective_only_feature_names,
)


def test_all_declared_packs_build() -> None:
    packs = all_feature_packs()
    assert set(packs) == set(FEATURE_PACKS)
    base = set(base_feature_names())
    assert base
    for name, spec in packs.items():
        assert spec.name == name
        assert set(spec.base_features) == base
        assert spec.excludes_news is True
        assert not set(NEWS_FEATURE_NAMES) & set(spec.feature_names)


def test_intelligence_full_excludes_news() -> None:
    full = build_feature_pack(PACK_INTELLIGENCE_FULL)
    assert "news" not in full.additive_domains
    assert set(prospective_only_feature_names()) == set(NEWS_FEATURE_NAMES)
    assert set(NEWS_FEATURE_NAMES).isdisjoint(full.feature_names)


def test_additive_packs_extend_base() -> None:
    base = build_feature_pack("BASE")
    rich = build_feature_pack("BASE+RICH_FUNDAMENTAL")
    assert rich.feature_names[: len(base.feature_names)] == base.feature_names
    assert len(rich.feature_names) > len(base.feature_names)
    assert "fund_roe" in rich.feature_names
    assert "fund_net_margin" in rich.feature_names


def test_feature_group_definitions_stable_keys() -> None:
    groups = feature_group_definitions()
    assert set(groups) == set(FEATURE_PACKS)
    assert "Dataset V5" not in str(groups)
