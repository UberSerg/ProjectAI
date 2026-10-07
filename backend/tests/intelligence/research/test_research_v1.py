"""Intelligence Research V1 is not Dataset V5 and does not promote Candidate."""

from app.modules.intelligence.research import (
    EXPERIMENT_NAME,
    FEATURE_PACKS,
    build_research_plan,
)
from app.modules.intelligence.research.packs import prospective_only_feature_names


def test_research_plan_is_not_dataset_v5() -> None:
    plan = build_research_plan()
    assert plan["experiment_name"] == EXPERIMENT_NAME
    assert plan["is_dataset_v5"] is False
    assert plan["candidate_promotion"] is False
    assert plan["retunes_v4"] is False
    assert "Dataset V5" not in str(plan)
    names = {row["pack"] for row in plan["coverage_matrix"]["packs"]}
    assert set(FEATURE_PACKS) <= names
    news = prospective_only_feature_names()
    assert news
    assert "news_material_event_count_7d" in news
