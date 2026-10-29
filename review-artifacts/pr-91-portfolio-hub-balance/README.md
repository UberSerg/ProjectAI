# Review artifacts — PR #91

## Feature
Portfolio Hub Balance — total NAV on `/portfolio` cards (fail-closed partial).

## Commit
`65122842c6a5a325a312574bdae4004df8c786b1`

## Artifacts

| File | What it shows |
|---|---|
| `01-hub-desktop-full-nav.png` | Live desktop hub: two portfolios with complete valuation; totals = cash + securities; cash `3,34 ₽` formatted correctly. |
| `02-hub-desktop-partial-unavailable.png` | Desktop hub: card with forced partial UI — «Общая стоимость недоступна» + «Оценённая часть» + missing-price warning (overlay for visual review; live marks were complete). |

## Notes
- Overlay of hub feature onto running Docker mounts (shadow-reliability) for browser capture only; mounts restored afterward.
- Mobile CSS breakpoint did not collapse sidebar in Emulation; desktop shots are primary visual evidence.
- Do not treat forced-partial screenshot as evidence of missing live quotes.
