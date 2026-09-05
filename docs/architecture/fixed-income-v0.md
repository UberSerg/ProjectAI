# Fixed Income V0 / Cashflow V1

V0 хранит условия облигации отдельно от `market.instruments`: `investment.bond_terms`,
`bond_cashflows`, `bond_market_snapshots`. Инструмент остаётся в master с
`asset_class=bond`.

Cashflow V1 добавляет официальный график из MOEX bondization (`coupons` /
`amortizations` / `offers`) без угаданных сумм. См. `fixed-income-cashflow-v1.md`.

Поддерживаемый класс для `SUPPORTED` — vanilla RUB fixed-rate с полным наблюдаемым
графиком купонов, без будущей оферты и без сложной амортизации.
Государственные, корпоративные и муниципальные облигации классифицируются отдельно.
Корпоративная облигация с `credit_quality_status=UNKNOWN` не пригодна для реального портфеля
даже при `SUPPORTED` учёте потоков.

Cashflow-типы: `COUPON`, `AMORTIZATION`, `REDEMPTION`, `OFFER`. Оферта не является
автоматическим погашением; без политики исполнения статус `RESEARCH_ONLY`.

Стоимость покупки: номинал × чистая цена в процентах + НКД + комиссии. Налоги имеют статус
`NOT_MODELED`, режим расчётов — `SETTLEMENT_NOT_MODELED_V0`.

Валюта номинала берётся из `FACEUNIT`. На ОФЗ MOEX часто отдаёт `SUR` — это российский
рубль и нормализуется в canonical `RUB` (с сохранением raw value). `CURRENCYID` на доске —
settlement/quotation и **не** подменяет валюту номинала: при `FACEUNIT=USD` и
`CURRENCYID=SUR` бумага остаётся FX face.
