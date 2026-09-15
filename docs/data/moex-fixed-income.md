# MOEX Fixed Income: аудит V0 / Cashflow V1

Источник — MOEX ISS, рынки облигаций, доски `TQOB` и `TQCB`. Команда
`python -m app.modules.investment.cli fixed-income-audit --live --limit 20` делает только
ограниченную выборку (максимум 100 строк на доску).

График купонов / амортизаций / оферт: см. `moex-bond-cashflows.md`
(` /iss/securities/{secid}/bondization.json `).

## Валютные поля (подтверждено live audit)

| Поле | Роль | Notes |
|------|------|-------|
| `FACEUNIT` | Валюта номинала | MOEX: face-value currency. На ОФЗ часто `SUR` = российский рубль → canonical `RUB`. |
| `CURRENCYID` | Settlement / quotation | На TQOB/TQCB часто `SUR` даже при `FACEUNIT=USD/CNY`. **Не** использовать как face currency. |
| `SEC_CURRENCY` | — | В используемом board securities payload не наблюдается. |

Каноническая валюта ProjectAI — `RUB`. Raw MOEX value сохраняется в provenance (`raw_fields.FACEUNIT`).

Клиент не выдумывает купонный график. Суммы купонов берутся только из bondization `value`.
Если будущие купоны без суммы / есть будущая оферта / сложная амортизация — `RESEARCH_ONLY`.
Планировщик обновления fixed income выключен.
