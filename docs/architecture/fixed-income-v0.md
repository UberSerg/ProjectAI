# Fixed Income V0

V0 хранит условия облигации отдельно от `market.instruments`: `investment.bond_terms`,
`bond_cashflows`, `bond_market_snapshots`. Инструмент остаётся в master с
`asset_class=bond`.

Поддерживаемый исследовательский класс — vanilla RUB fixed-rate без неоднозначной семантики.
Государственные, корпоративные и муниципальные облигации классифицируются отдельно.
Корпоративная облигация с `credit_quality_status=UNKNOWN` не пригодна для реального портфеля.

Cashflow-типы: `COUPON`, `AMORTIZATION`, `REDEMPTION`, `OFFER`. Оферта не является
автоматическим погашением; без политики исполнения статус `RESEARCH_ONLY`.

Стоимость покупки: номинал × чистая цена в процентах + НКД + комиссии. Налоги имеют статус
`NOT_MODELED`, режим расчётов — `SETTLEMENT_NOT_MODELED_V0`.

Валюта лица бумаги берётся из `FACEUNIT`, а не из `CURRENCYID`: на TQOB/TQCB часто
`CURRENCYID=SUR` при иностранном номинале. Такие выпуски — `UNSUPPORTED` / `RESEARCH_ONLY`,
не «рублёвая vanilla».
