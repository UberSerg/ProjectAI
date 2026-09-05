# MOEX Fixed Income: аудит V0

Источник — MOEX ISS, рынки облигаций, доски `TQOB` и `TQCB`. Команда
`python -m app.modules.investment.cli fixed-income-audit --live --limit 20` делает только
ограниченную выборку (максимум 100 строк на доску).

## Валютные поля (подтверждено live audit)

| Поле | Роль | Notes |
|------|------|-------|
| `FACEUNIT` | Валюта номинала | MOEX: face-value currency. На ОФЗ часто `SUR` = российский рубль → canonical `RUB`. |
| `CURRENCYID` | Settlement / quotation | На TQOB/TQCB часто `SUR` даже при `FACEUNIT=USD/CNY`. **Не** использовать как face currency. |
| `SEC_CURRENCY` | — | В используемом board securities payload не наблюдается. |

Каноническая валюта ProjectAI — `RUB`. Raw MOEX value сохраняется в provenance (`raw_fields.FACEUNIT`).

Клиент не выдумывает купонный график. Если тип купона не подтверждён источником, support =
`RESEARCH_ONLY`. Планировщик обновления fixed income в V0 выключен.
