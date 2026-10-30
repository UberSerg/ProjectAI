# Kraken Design System V2 — Token Contract

Owner: Agent 01 (Design System). Branch: `ux/design-system-v2`.

Cascade in `frontend/src/main.tsx`:

```text
styles.css            → legacy layout / feature chrome (do not add new global colours)
design-system.css     → light token owner + shared primitives
styles/kraken-dark.css → dark token owner + cockpit chrome (loaded last)
```

Theme switch sets `data-theme="light|dark"` on `<html>`. Dark wins at equal specificity because it loads last.

## Surfaces

| Role | Prefer | Legacy alias |
|---|---|---|
| Background (page) | `--kr-bg` / `--surface-background` / `--surface-page` | `--bg` |
| Surface (cards/panels) | `--kr-surface` / `--surface` / `--surface-panel` | `--panel` |
| Elevated (menus, modals) | `--kr-elevated` / `--surface-elevated` | `--bg-elevated` |
| Overlay (dimmers) | `--kr-overlay` / `--overlay` | — |
| Raised / subtle / sunken | `--surface-raised`, `--surface-subtle`, `--surface-sunken` | — |

## Text

| Role | Token |
|---|---|
| Primary | `--kr-text` / `--text-primary` / `--ink` |
| Secondary | `--kr-text-secondary` / `--text-secondary` / `--ink-secondary` |
| Muted | `--kr-text-muted` / `--text-muted` / `--muted` |
| Inverse (on accent) | `--text-inverse` |

## Border / focus

| Role | Token |
|---|---|
| Border | `--kr-border` / `--border` / `--line` |
| Strong border | `--kr-border-strong` / `--border-strong` / `--line-strong` |
| Focus ring | `--kr-focus` / `--focus-ring` / `--accent` |

## Status meaning (Success / Danger / Warning / Info)

| Meaning | FG | BG | Line |
|---|---|---|---|
| Success | `--kr-success` / `--success` | `--success-bg` | `--success-line` |
| Danger | `--kr-danger` / `--danger` / `--error` | `--danger-bg` | `--danger-line` |
| Warning | `--kr-warning` / `--warning` | `--warning-bg` | `--warning-line` |
| Info | `--kr-info` / `--info` / `--running` | `--info-bg` | `--info-line` |

Colour encodes meaning — do not use accent blue for P&L or danger.

## Decision actions (BUY / SELL / HOLD / REVIEW)

| Action | Tokens | CSS / component |
|---|---|---|
| BUY | `--action-buy`, `--action-buy-bg` | `.ds-action-buy` / `DecisionActionChip` |
| SELL | `--action-sell`, `--action-sell-bg` | `.ds-action-sell` |
| HOLD | `--action-hold`, `--action-hold-bg` | `.ds-action-hold` |
| REVIEW | `--action-review`, `--action-review-bg` | `.ds-action-review` |

## Freshness (FRESH / STALE / PARTIAL / UNAVAILABLE)

| State | Tokens | Component |
|---|---|---|
| FRESH | `--freshness-fresh*` | `FreshnessBadge` / `.ds-freshness-fresh` |
| STALE | `--freshness-stale*` | `.ds-freshness-stale` |
| PARTIAL | `--freshness-partial*` | `.ds-freshness-partial` |
| UNAVAILABLE | `--freshness-unavailable*` | `.ds-freshness-unavailable` |

`Missing ≠ 0`. Prefer `FreshnessBadge` / `DataQualityNote` over inventing zero values.

## Provenance (LIVE / COUNTERFACTUAL)

| State | Tokens | Component |
|---|---|---|
| LIVE | `--provenance-live*` | `ProvenanceBadge` / `.ds-provenance-live` |
| COUNTERFACTUAL | `--provenance-counterfactual*` | `.ds-provenance-counterfactual` |

## Typography / spacing / radius / elevation / motion

| Scale | Tokens |
|---|---|
| Type | `--text-xs` … `--text-hero`, `--text-number` (important figures) |
| Fonts | `--font`, `--font-mono` (light: Inter; dark: Manrope + JetBrains Mono) |
| Spacing | `--space-1` … `--space-6` |
| Radius | `--radius-sm`, `--radius-md`, `--radius-lg` |
| Elevation | `--elevation-0`, `--elevation-1`, `--elevation-2` |
| Motion | `--motion-fast|base|slow`, `--ease-standard`; respect `prefers-reduced-motion` |
| Breakpoints (reference) | `--bp-sm` 520, `--bp-md` 900, `--bp-lg` 1100, `--bp-xl` 1180 |

## Primitives (`frontend/src/components/Ui.tsx`)

Reuse these — do not fork one-off badge markup in Journal/Shadow:

- `PageHeader`, `MetricCard`, `HeroCard`, `StatusBadge`
- `DecisionActionChip`, `FreshnessBadge`, `ProvenanceBadge`
- `InlineNotice`, `DataQualityNote`, `DataQualityCard`
- `Accordion`, `EmptyState`, `ErrorState`, `LoadingSkeleton`, `PageState`
- Warning / Risk / Explanation cards

UX rules: one centre per card; important numbers use `.ds-number` / `--text-number`; loading via `LoadingSkeleton` (no layout jump, no fake zeros); errors via `ErrorState` / `PageState kind="error"`.

## Handoff for Agent 02 (Journal V4)

Prefer:

```tsx
import {
  Accordion,
  DecisionActionChip,
  FreshnessBadge,
  ProvenanceBadge,
  InlineNotice,
  DataQualityNote,
  EmptyState,
  ErrorState,
  LoadingSkeleton,
} from "../../components/Ui";
```

CSS classes if you need bare markup: `.ds-accordion`, `.ds-action-*`, `.ds-freshness-*`, `.ds-provenance-*`, `.ds-inline-notice-*`, `.ds-data-quality-note`, `.ds-number`.

Do **not** edit `design-system.css` / `kraken-dark.css` / `Ui.tsx` from Agent 02 — scope CSS under Decision Journal feature files only.
