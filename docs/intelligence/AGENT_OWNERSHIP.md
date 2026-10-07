# Intelligence Stack V1 — Agent File Ownership

Orchestrator owns shared contracts. Agents request contract changes; they do not rewrite them unilaterally.

| Agent | Branch (local only) | Owned paths |
|-------|---------------------|-------------|
| A intraday | `agent/intel-a-intraday` | `intelligence/intraday/*`, MOEX candle interval fetch extensions under `infrastructure/market/` (additive), tests `tests/intelligence/intraday/` |
| B fundamentals | `agent/intel-b-fundamentals` | `intelligence/fundamentals/*` (industrial snapshot; reuse `modules/fundamentals`) |
| C banks | `agent/intel-c-banks` | `intelligence/banks/*` |
| D news | `agent/intel-d-news` | `intelligence/news/*` (fill empty `modules/news` only if needed via orchestrator) |
| E LLM extract | `agent/intel-e-llm` | `intelligence/extraction/*` |
| F knowledge | `agent/intel-f-knowledge` | `intelligence/knowledge/*`, `docs/intelligence/knowledge_packs/` |
| G macro | `agent/intel-g-macro` | `intelligence/macro/*` |
| H signals | `agent/intel-h-signals` | `intelligence/signals/*` |
| I committee | `agent/intel-i-committee` | `intelligence/committee/*` |
| J risk | `agent/intel-j-risk` | `intelligence/risk/*` (do not mutate `modules/risk` product semantics without orchestrator) |
| K research | `agent/intel-k-research` | `intelligence/research/*` |
| L API/UI | `agent/intel-l-api-ui` | `api/v1/intelligence.py`, `frontend/src/pages/intelligence/*`, `frontend/src/api/intelligence*` |
| M operations | `agent/intel-m-operations` | `intelligence/operations/*`, workflow wiring |
| N red team | `agent/intel-n-red-team` | `tests/intelligence/adversarial/*` |
| O performance | `agent/intel-o-performance` | indexes in consolidated migration (via orchestrator), `intelligence/quality/*` |

## Shared (orchestrator only)

- `intelligence/contracts/*`
- `intelligence/__init__.py`
- `docs/architecture/kraken-intelligence-stack-v1.md`
- consolidated Alembic migration for `intelligence` schema
- `KRAKEN_CURRENT_STATE.md` updates at campaign end only

## Commit policy

Local commits only. No push. No individual PRs.  
Focused tests + Ruff on touched Python before commit.
