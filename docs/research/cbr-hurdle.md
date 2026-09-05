# CBR Hurdle

Источник не дублируется: используется существующий `market.series(code=KEY_RATE)` и
`market.series_values`, загружаемые через SOAP `KeyRateXML`.

Для точки решения `t` выбирается только наблюдение с датой не позже `t`. Точность доступности
в V0 — `DATE_ONLY`: `known_at` равен дате наблюдения. Ставка не применяется до этой даты.

Для горизонтов 1d/5d/10d/20d/1m/3m/1y:

`hurdle = (1 + annual_rate)^(N / 252) - 1`.

Для исторического периода ставка начисляется кусочно по календарным дням. В результат
симуляции добавляются `hurdle_return`, `excess_vs_cbr`, `cbr_hurdle_verdict`; исходные данные
Forward, Shadow и Prospective A/B не меняются. Verdict: `BEATS_HURDLE`,
`BELOW_HURDLE` или `INCONCLUSIVE`.
