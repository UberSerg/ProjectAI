# Review artifacts — PR #59

## Feature
Kraken Personal V1 dark desktop dashboard (cockpit + contrast polish).

## Commit
Feature HEAD: `98a173a` (`feat(frontend): Kraken Personal V1 dark desktop cockpit`)
Rule commit on same branch: `702be2e`

## Artifacts

| File | What it shows |
|---|---|
| `01-dashboard-overview.png` | Full desktop Обзор cockpit: hero NAV, allocation, empty NAV chart, health, recommendations |
| `02-portfolio-recommendations.png` | Block «Что Kraken предлагает сделать» with Сократить/Докупить + Подробнее CTAs |
| `03-capital-input-focused.png` | Мой портфель — dark cash input + Сохранить кэш (readable focus/contrast) |
| `04-rebalance-active-tab.png` | Active «Ребаланс» tab: advisory plan table, not blue-on-blue |
| `05-empty-nav-history.png` | Empty NAV history card («История стоимости пока недоступна») instead of fake chart |

## Notes
- Check input/button contrast on dark theme.
- Recommendations should read as primary actions with clear Подробнее.
- Rebalance tab underline/active state must stay visible on dark chrome.
- Do **not** cleanup this folder until PR #59 is merged/closed and CI is green.
