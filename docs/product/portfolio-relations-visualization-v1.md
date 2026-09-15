# Portfolio Relations Visualization — UX V2

Presentation layer on top of Portfolio Relations Visualization V1 API.

## What changed (UX only)

On **Портфель Kraken**, block **Связи внутри портфеля** now leads with:

1. **Human-readable summary** (deterministic, no LLM)
2. **Network graph** of supported instruments
3. **Missing-data** list (unsupported FI / no Relations input)
4. Collapsible **Подробные связи** — triangular heatmap with exact Pearson values

KPI cards (`6/15`, mean |corr|, LEVEL 1/2) are removed from the primary surface.

## Data source (unchanged)

`POST /api/v1/relations/portfolio` + `build_portfolio_relations_matrix`:

- Pearson on `log_return_1d`
- Window 60 trading days (default)
- Coverage ≥ 0.8
- Latest persisted `as_of` per pair
- `pearson: null` for missing — never coerced to 0
- Cash excluded; ≤12 symbols

## Deterministic summary rules (UX-only / presentation)

Thresholds (`PRESENTATION_STRONG_POSITIVE` = 0.70, moderate 0.40, negative −0.40) are
**presentation-only**. They do **not** affect Candidate, Risk Gate, Allocation, or
persisted Relations research labels.

| Band | Threshold |
|------|-----------|
| Strong positive | ≥ 0.70 |
| Moderate positive | ≥ 0.40 and &lt; 0.70 |
| Meaningful negative | ≤ −0.40 |

**Tight group («группа тесно связанных»)** = strong **clique**, not mere connectivity:

1. size ≥ 3;
2. every pairwise correlation among members is available;
3. every pairwise Pearson ≥ 0.70.

A path of strong edges (e.g. A–B=0.80, B–C=0.80, A–C=0.10) is **not** a tight group.

Algorithm:

1. Supported = instruments with Relations input READY.
2. Available pairs = cells with `status=OK` and non-null pearson.
3. Find largest strong clique among instruments that appear in available pairs.
4. If clique size ≥ 3 → «группа тесно связанных»; other supported with max corr to clique &lt; 0.70 → «связан слабее».
5. Else if any strong pair → «тесная пара, но не большая группа» (may note that a strong chain is not a tight group).
6. Else → «выраженной группы не обнаружено» (may mention moderate/negative).
7. If no available pairs / &lt;2 supported → insufficient-data copy.

No buy/sell language. No portfolio score.

## Network graph

- Nodes: READY instruments only
- Edges: available pairs only (missing → no edge; absent edge ≠ 0)
- Stroke weight/opacity by |correlation|; muted palette
- Positive / non-negative edges: **solid**; negative edges: **dashed** (not color-only)
- Labels on |r| ≥ 0.40 (numeric label keeps the minus sign)
- Deterministic circular layout (clique members ordered first)
- No new chart dependency (SVG)

## Heatmap details

- Upper triangle only; no diagonal 1.00; each pair once
- N/A remains N/A
- Collapsed by default under «Подробные связи»

## Investment semantics

Unchanged: Candidate, Policy, Risk Gate, Explanation, Prediction, universes, Relations calculation.
