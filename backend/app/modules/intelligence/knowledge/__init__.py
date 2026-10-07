"""Knowledge Engine — versioned investment principles, not trade orders."""

from app.modules.intelligence.knowledge.contradictions import (
    ContradictionReport,
    detect_contradictions,
)
from app.modules.intelligence.knowledge.evaluator import (
    RuleEvaluationContext,
    evaluate_rule,
    evaluate_rules,
)
from app.modules.intelligence.knowledge.ingest import (
    KnowledgePack,
    default_knowledge_packs_dir,
    ingest_path,
    load_pack_file,
    load_packs_from_dir,
)
from app.modules.intelligence.knowledge.repository import (
    InMemoryKnowledgeRuleStore,
    KnowledgeRuleStore,
    PersistOutcome,
    PersistResult,
)
from app.modules.intelligence.knowledge.service import KnowledgeEngine, KnowledgeEngineReport

__all__ = [
    "ContradictionReport",
    "InMemoryKnowledgeRuleStore",
    "KnowledgeEngine",
    "KnowledgeEngineReport",
    "KnowledgePack",
    "KnowledgeRuleStore",
    "PersistOutcome",
    "PersistResult",
    "RuleEvaluationContext",
    "default_knowledge_packs_dir",
    "detect_contradictions",
    "evaluate_rule",
    "evaluate_rules",
    "ingest_path",
    "load_pack_file",
    "load_packs_from_dir",
]
