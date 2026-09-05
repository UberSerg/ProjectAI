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

Валюта номинала берётся из `FACEUNIT`. На ОФЗ MOEX часто отдаёт `SUR` — это российский
рубль и нормализуется в canonical `RUB` (с сохранением raw value). `CURRENCYID` на доске —
settlement/quotation и **не** подменяет валюту номинала: при `FACEUNIT=USD` и
`CURRENCYID=SUR` бумага остаётся FX face.
