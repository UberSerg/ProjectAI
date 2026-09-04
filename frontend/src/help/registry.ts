import type { HelpEntry, PageHelpContent } from "./types";

/** One source of truth for tooltips, expanded metric help, and page справка. */
export const HELP_METRICS: Record<string, HelpEntry> = {
  last_price: {
    id: "last_price",
    kind: "metric",
    title: "Последняя цена",
    summary: "Close последней доступной дневной RAW-свечи.",
    details:
      "Цена закрытия последнего торгового дня, который есть в market.candles. Это не adjusted и не total-return цена.",
    interpretation: "Сравнивайте с предыдущими close только в контексте RAW-истории.",
    limitations: ["Не учитывает дивиденды.", "Не пересчитывается после сплитов в этом UI."],
  },
  return_1d: {
    id: "return_1d",
    kind: "metric",
    title: "Доходность 1 день",
    summary: "Относительное изменение close за 1 торговый день.",
    details: "Базовый признак Analytics: (close_t − close_{t−1}) / close_{t−1} на точке as-of t.",
    interpretation: "Короткий шум; сам по себе не сигнал к сделке.",
    limitations: ["Нужна достаточная история.", "Считается по RAW close."],
    relatedIds: ["return_5d", "return_20d"],
  },
  return_5d: {
    id: "return_5d",
    kind: "metric",
    title: "Доходность 5 дней",
    summary: "Изменение close за 5 торговых дней.",
    details: "Окно ~одной торговой недели по дневным свечам.",
    interpretation: "Показывает краткосрочный импульс, не прогноз.",
    relatedIds: ["return_1d", "return_20d"],
  },
  return_20d: {
    id: "return_20d",
    kind: "metric",
    title: "Доходность 20 дней",
    summary: "Изменение close за ~20 торговых дней (~месяц).",
    details:
      "Используется в Analytics и как вход Technical. На экране инструмента показывается значение из активного feature set. Mechanical-adjusted V2 — отдельный расчётный контур, не замена RAW-графика котировок.",
    interpretation: "Среднесрочный импульс. Высокое значение ≠ рекомендация покупать.",
    limitations: [
      "Не вероятность прибыли.",
      "На инструментах с короткой историей может быть «Недостаточно истории».",
    ],
    relatedIds: ["return_5d", "rsi14", "confidence"],
  },
  volatility_5d: {
    id: "volatility_5d",
    kind: "metric",
    title: "Волатильность 5 дней",
    summary: "Краткосрочная вариативность доходностей.",
    details: "Оценка разброса дневных доходностей на окне 5 дней.",
    interpretation: "Высокая волатильность = шире разброс исходов, не направление.",
  },
  volatility_20d: {
    id: "volatility_20d",
    kind: "metric",
    title: "Волатильность 20 дней",
    summary: "Вариативность доходностей на ~месячном окне.",
    details: "Более устойчивая оценка шума, чем 5-дневная.",
    interpretation: "Сравнивайте внутри одного инструмента и режима рынка.",
  },
  drawdown_20d: {
    id: "drawdown_20d",
    kind: "metric",
    title: "Просадка 20 дней",
    summary: "Падение от локального максимума на окне 20 дней.",
    details: "Отрицательная величина: насколько close ниже недавнего пика.",
    interpretation: "Мера локального давления продаж, не «риск портфеля».",
  },
  volume_change_1d: {
    id: "volume_change_1d",
    kind: "metric",
    title: "Изменение объёма",
    summary: "Относительное изменение дневного объёма к предыдущему дню.",
    details: "Показывает всплеск или спад активности торгов.",
  },
  volume_zscore_20d: {
    id: "volume_zscore_20d",
    kind: "metric",
    title: "Z-score объёма 20д",
    summary: "Насколько текущий объём отклоняется от среднего за 20 дней.",
    details: "Z ≈ 0 — около нормы; |Z| > 2 — заметный выброс активности.",
    interpretation: "Подтверждение импульса, не самостоятельный сигнал.",
  },
  technical_score: {
    id: "technical_score",
    kind: "metric",
    title: "Score",
    summary: "Сводный балл rules_v1 по факторам тренда, моментума, RSI и объёма.",
    details:
      "Детерминированная rules-модель Technical Agent. Score — агрегат вкладов факторов, а не ожидаемая доходность.",
    interpretation: "Знак и величина отражают согласованность правил на as-of дате.",
    limitations: ["Не BUY/SELL.", "Не прогноз цены."],
    relatedIds: ["confidence", "rsi14"],
  },
  confidence: {
    id: "confidence",
    kind: "metric",
    title: "Confidence",
    summary: "Насколько согласован и полон сигнал (coverage × agreement × quality) — не вероятность прибыли.",
    details:
      "Считается как coverage × agreement × quality (0…1). Coverage — сколько факторов доступно; agreement — совпадают ли их знаки; quality — штраф за проблемы данных.",
    interpretation:
      "Высокий confidence значит «оценка собрана согласованно», а не «сделка с высокой вероятностью прибыли».",
    limitations: [
      "Это не вероятность прибыли и не калиброванная вероятность направления.",
      "При разрыве цены / невалидных данных сигнал обнуляется.",
    ],
    relatedIds: ["technical_score", "rsi14"],
  },
  rsi14: {
    id: "rsi14",
    kind: "metric",
    title: "RSI14",
    summary: "Индекс относительной силы за 14 торговых дней.",
    details:
      "Осциллятор моментума по дневным close. В rules_v1 — один из входов в score, а не самостоятельный торговый сигнал.",
    interpretation: "Зоны около 30/70 часто читают как перепроданность/перекупленность — в ProjectAI это вклад в оценку, не приказ.",
    limitations: ["На короткой истории может отсутствовать.", "Не использовать как единственное правило входа."],
    relatedIds: ["return_20d", "confidence"],
  },
  sma20_distance: {
    id: "sma20_distance",
    kind: "metric",
    title: "SMA20 dist",
    summary: "Относительное расстояние close к SMA(20).",
    details: "Положительное — цена выше средней; отрицательное — ниже.",
  },
  ema20_distance: {
    id: "ema20_distance",
    kind: "metric",
    title: "EMA20 dist",
    summary: "Относительное расстояние close к EMA(20).",
    details: "EMA быстрее реагирует на недавние close, чем SMA.",
  },
  atr14_pct: {
    id: "atr14_pct",
    kind: "metric",
    title: "ATR14%",
    summary: "Average True Range 14, нормированный к цене.",
    details: "Мера дневного «размаха» в процентах цены.",
    interpretation: "Выше ATR% — шире типичный дневной ход.",
  },
  pearson: {
    id: "pearson",
    kind: "metric",
    title: "Pearson",
    summary: "Линейная корреляция доходностей пары на окне.",
    details:
      "Relations Agent: статистическая связь двух inputs на выбранном окне наблюдений. Не причинность и не торговый сигнал.",
    interpretation: "Близко к ±1 — сильная линейная согласованность; около 0 — слабая.",
    limitations: ["Не означает lead-lag.", "Не рекомендация к парной торговле."],
    relatedIds: ["spearman", "best_lag", "relations_term"],
  },
  spearman: {
    id: "spearman",
    kind: "metric",
    title: "Spearman",
    summary: "Ранговая корреляция на том же окне.",
    details: "Устойчивее к выбросам, чем Pearson; всё ещё описательная статистика.",
    relatedIds: ["pearson"],
  },
  best_lag: {
    id: "best_lag",
    kind: "metric",
    title: "Best lag",
    summary: "Лучший лаг lead→follower по корреляции на профиле лагов.",
    details:
      "Эвристика синхронности/опережения на исторических доходностях. Не доказательство причинности и не гарантия будущего опережения.",
    limitations: ["Может меняться между as_of датами.", "Не торговый сигнал."],
    relatedIds: ["pearson", "relations_term"],
  },
  relations_term: {
    id: "relations_term",
    kind: "term",
    title: "Связи (Relations)",
    summary: "Статистическая структура рынка: корреляции и lead-lag, не BUY/SELL.",
    details:
      "Модуль Relations считает snapshots корреляций и лагов между inputs. Это слой описания структуры, а не исполнение сделок. Mechanical V2 adjustment — отдельный контур данных; UI показывает активный relation set.",
    interpretation: "Используйте для понимания «кто движется вместе», а не для автоматических ордеров.",
    limitations: [
      "Корреляция ≠ причинность.",
      "Окно и universe влияют на топ пар.",
      "Не активирует торговый контур.",
    ],
    relatedIds: ["pearson", "best_lag"],
  },
  raw_candles: {
    id: "raw_candles",
    kind: "term",
    title: "RAW свечи",
    summary: "Биржевые дневные OHLCV как пришли с биржи — без «сглаживания» сплитов.",
    details:
      "На графике котировок ProjectAI показывает RAW exchange candles (market.candles). Механические сплиты/деноминации не переписывают эти свечи: разрыв цены после сплита остаётся видимым. Отдельная analytical basis ProjectAI (mechanical-adjusted) используется в Analytics / Technical / Relations и не подменяет этот график.",
    limitations: [
      "Дивидендные гэпы тоже остаются как есть.",
      "Adjusted-график в этом UI не показывается — это сознательное разделение Prediction/Analytics vs сырых котировок.",
    ],
  },
  feature_coverage: {
    id: "feature_coverage",
    kind: "metric",
    title: "Покрытие инструментов",
    summary: "Сколько активных инструментов имеют рассчитанные признаки.",
    details: "Отношение instruments_with_features / instruments_active для активного feature set.",
  },
  data_quality: {
    id: "data_quality",
    kind: "metric",
    title: "Качество данных",
    summary: "Сводка DQ-замечаний по инструменту или рынку.",
    details: "Append-only журнал проблем качества: пропуски, скачки, пустые ответы источника и т.п.",
    interpretation: "«Без замечаний» не гарантирует идеальные данные навсегда — только отсутствие текущих записей DQ.",
  },
  sim_nav: {
    id: "sim_nav",
    kind: "metric",
    title: "NAV симуляции",
    summary: "Стоимость виртуального портфеля Historical Simulator V0 на дату.",
    details:
      "NAV = cash + сумма market value позиций по RAW close/open правилам исполнения. Это research ledger, не брокерский счёт.",
    interpretation: "Сравнивайте динамику NAV с нормализованным IMOEX на том же окне.",
    limitations: ["Не включает дивидендный cash в V0.", "Не реальное исполнение у брокера."],
    relatedIds: ["sim_cash", "sim_exposure"],
  },
  sim_cagr: {
    id: "sim_cagr",
    kind: "metric",
    title: "Доходность / CAGR",
    summary: "Price return портфеля (и CAGR при достаточной длине окна).",
    details:
      "total_price_return = final_nav / initial_nav − 1. CAGR считается только на достаточно длинных окнах. Тип возврата — price, не total return.",
    interpretation: "Отрицательная абсолютная доходность красится как убыток; это не то же самое, что относительный результат к IMOEX.",
    limitations: ["Без дивидендов.", "Не гарантия будущей прибыли."],
    relatedIds: ["sim_excess", "sim_max_drawdown"],
  },
  sim_volatility: {
    id: "sim_volatility",
    kind: "metric",
    title: "Волатильность портфеля",
    summary: "Годовая волатильность дневных доходностей NAV (research).",
    details: "Оценка разброса дневных return NAV, аннуализированная на 252 торговые дни.",
    interpretation: "Мера шума доходности, не направление.",
    relatedIds: ["sim_sharpe"],
  },
  sim_sharpe: {
    id: "sim_sharpe",
    kind: "metric",
    title: "Sharpe (rf=0)",
    summary: "Research Sharpe без безрисковой ставки — не брокерский реализм.",
    details: "Средняя дневная доходность / дневная σ, × √252, rf = 0. Нужна для сравнения режимов, не для отчётности инвестору.",
    limitations: ["rf=0.", "Чувствителен к окну и издержкам."],
    relatedIds: ["sim_volatility", "sim_cagr"],
  },
  sim_max_drawdown: {
    id: "sim_max_drawdown",
    kind: "metric",
    title: "Максимальная просадка",
    summary: "Худшее падение NAV от пика к дну на периоде симуляции.",
    details: "Считается по дневной серии NAV. UI показывает даты пика, дна и (если есть) восстановления.",
    interpretation: "Риск пути капитала, не «вероятность убытка».",
    relatedIds: ["sim_nav", "sim_cagr"],
  },
  sim_turnover: {
    id: "sim_turnover",
    kind: "metric",
    title: "Оборот",
    summary: "Отношение суммарного notional сделок к среднему NAV.",
    details: "Грубый proxy торговой активности. Высокий оборот усиливает влияние commission/slippage bps.",
    relatedIds: ["sim_commission", "sim_bps"],
  },
  sim_exposure: {
    id: "sim_exposure",
    kind: "metric",
    title: "Gross exposure",
    summary: "Суммарная рыночная стоимость длинных позиций.",
    details: "В long-only V0 совпадает с invested capital; cash хранится отдельно.",
    relatedIds: ["sim_cash", "sim_nav"],
  },
  sim_cash: {
    id: "sim_cash",
    kind: "metric",
    title: "Cash",
    summary: "Свободные денежные средства ledger на дату.",
    details: "Остаток после покупок/продаж и комиссий. Cash weight = cash / NAV.",
    relatedIds: ["sim_nav", "sim_exposure"],
  },
  sim_excess: {
    id: "sim_excess",
    kind: "metric",
    title: "Относительный результат (п.п.)",
    summary: "Разность price return портфеля и IMOEX в процентных пунктах.",
    details:
      "excess_vs_imoex = total_price_return_portfolio − total_price_return_IMOEX. Положительный excess при отрицательной абсолютной доходности означает «упали меньше индекса», а не «заработали».",
    interpretation: "Не путать с прибылью портфеля. В UI оформляется нейтрально, не как green profit.",
    limitations: ["IMOEX — price index.", "Не alpha в смысле CAPM."],
    relatedIds: ["sim_cagr"],
  },
  sim_bps: {
    id: "sim_bps",
    kind: "metric",
    title: "Издержки (bps)",
    summary: "Комиссия/проскальзывание в базисных пунктах на сделку.",
    details: "Упрощённая friction-модель V0. Cost-sensitivity сравнивает sibling-прогоны с разными bps.",
    relatedIds: ["sim_commission", "sim_slippage"],
  },
  sim_slippage: {
    id: "sim_slippage",
    kind: "metric",
    title: "Slippage (bps)",
    summary: "Модельное проскальзывание относительно raw open.",
    details: "Добавляется к цене исполнения в Historical Next Open adapter. Не рыночный impact-модель.",
    relatedIds: ["sim_bps", "sim_commission"],
  },
  sim_commission: {
    id: "sim_commission",
    kind: "metric",
    title: "Commission (bps)",
    summary: "Комиссия в bps от notional сделки.",
    details: "Списывается из cash при fill. Секция чувствительности показывает sibling SUCCESS runs.",
    relatedIds: ["sim_bps", "sim_turnover"],
  },
  sim_oos: {
    id: "sim_oos",
    kind: "term",
    title: "OOS / research-контекст",
    summary: "DEVELOPMENT_OOS и research-метка Candidate V0 (часто MIXED) — не gate прибыльности.",
    details:
      "Prediction ML Candidate V0 имеет research verdict MIXED. На дашборде симулятора это показывается как контекст исследования отдельно от engineering PASS. Нельзя читать MIXED как «модель прибыльна» или «готова к деньгам».",
    interpretation: "Сначала engineering status, затем research-контекст как осторожная пометка.",
    limitations: ["Не торговый сигнал.", "Не чемпион-статус."],
    relatedIds: ["sim_holdout"],
  },
  sim_holdout: {
    id: "sim_holdout",
    kind: "term",
    title: "FINAL_HOLDOUT",
    summary: "Финальный holdout-сегмент предсказаний — отдельный период от DEV OOS.",
    details:
      "Сравнение DEV vs HOLDOUT при 0 bps — образовательная таблица устойчивости на разных окнах, не proof of edge.",
    limitations: ["Один holdout не заменяет многократный walk-forward."],
    relatedIds: ["sim_oos"],
  },
  sim_rebalance: {
    id: "sim_rebalance",
    kind: "term",
    title: "Ребаланс",
    summary: "Weekly rebalance: целевые веса пересматриваются по политике на decision date.",
    details: "В V0 политика Rank Long-Only выбирает top quantile и задаёт target weights; ордера появляются в дни ребаланса.",
    relatedIds: ["sim_next_open"],
  },
  sim_next_open: {
    id: "sim_next_open",
    kind: "term",
    title: "Next open исполнение",
    summary: "Исполнение на следующем торговом open после decision date.",
    details: "HistoricalNextOpenAdapter: нет look-ahead на close дня решения. Fill price = raw open ± friction.",
    relatedIds: ["sim_rebalance", "sim_slippage", "decision_pending"],
  },
  decision_why: {
    id: "decision_why",
    kind: "term",
    title: "Почему была сделка?",
    summary:
      "Человекочитаемое объяснение из сохранённых фактов решения: прогноз, ранг, политика, риск, исполнение.",
    details:
      "Три уровня: краткое резюме, подробности правила политики, технические детали provenance. Текст строится детерминированно в UI из API-фактов. LLM не используется.",
    interpretation:
      "Модель даёт прогноз/ранг; политика задаёт целевую позицию; риск может ограничить экспозицию; исполнение — отдельный этап.",
    limitations: [
      "Не инвестиционная рекомендация.",
      "Не объясняет «почему цена потом выросла/упала».",
      "Неполная provenance → более короткое объяснение без выдуманных полей.",
    ],
    relatedIds: [
      "decision_pred_20d",
      "decision_rank",
      "decision_target_weight",
      "decision_policy",
      "decision_reason_code",
      "sim_next_open",
      "decision_pending",
      "decision_risk_guard",
      "decision_tech_provenance",
    ],
  },
  decision_pred_20d: {
    id: "decision_pred_20d",
    kind: "metric",
    title: "Predicted Return 20d",
    summary: "Прогноз модели механического изменения цены на 20 торговых дней (~месяц).",
    details:
      "Это forecast Candidate V0 по PIT-признакам, а не гарантированная доходность и не total return с дивидендами. Не рекомендация к покупке.",
    limitations: ["Не probability of profit.", "Не дивидендный total return."],
    relatedIds: ["decision_rank", "decision_why"],
  },
  decision_rank: {
    id: "decision_rank",
    kind: "metric",
    title: "Rank",
    summary: "Относительное место инструмента среди eligible прогнозов на дату.",
    details:
      "Rank 1 — наибольший predicted return 20d среди доступных на эту дату инструментов. Это не «лучшая компания».",
    relatedIds: ["decision_pred_20d", "decision_why"],
  },
  decision_target_weight: {
    id: "decision_target_weight",
    kind: "metric",
    title: "Target Weight",
    summary: "Целевая доля позиции, назначенная политикой на дату решения.",
    details:
      "Вес после policy (+ risk clamp, если применялся). Фактический fill может отличаться из‑за цен/кэша/округления.",
    relatedIds: ["decision_policy", "decision_why"],
  },
  decision_policy: {
    id: "decision_policy",
    kind: "term",
    title: "Policy",
    summary: "Правило, которое превращает прогнозы/ранги в целевые позиции.",
    details:
      "Например, рейтинговая стратегия с удержанием (Hysteresis V1): вход Top 20%, удержание до Top 35%, порог сделки 2 п.п. Модель сама не «покупает».",
    relatedIds: ["decision_reason_code", "decision_why"],
  },
  decision_reason_code: {
    id: "decision_reason_code",
    kind: "term",
    title: "Reason Code",
    summary: "Технический код причины ордера/решения (ENTER_TOP20, EXIT_BELOW_TOP35, …).",
    details:
      "В UI сначала показывается человеческое объяснение; код остаётся в технических деталях для аудита.",
    relatedIds: ["decision_why", "decision_tech_provenance"],
  },
  decision_pending: {
    id: "decision_pending",
    kind: "term",
    title: "Pending Order",
    summary: "Ордер создан, но ещё не исполнен — ждёт допустимое будущее открытие рынка.",
    details:
      "Для Shadow Portfolio fill запрещён на уже известных прошлых OPEN. Пока нет qualifying future open, корректный статус — PENDING.",
    relatedIds: ["sim_next_open", "decision_why"],
  },
  decision_risk_guard: {
    id: "decision_risk_guard",
    kind: "term",
    title: "Risk Guard",
    summary: "Ограничение экспозиции по собственной просадке портфеля (DRAWDOWN_GUARD_V1).",
    details:
      "При просадке ≤ −20% gross → 50%; при восстановлении ≥ −10% → 100%. Работает по Shadow/Simulator NAV этого портфеля, не по прогнозу модели.",
    relatedIds: ["decision_why", "sim_max_drawdown"],
  },
  decision_tech_provenance: {
    id: "decision_tech_provenance",
    kind: "term",
    title: "Technical provenance",
    summary: "Сырые поля решения/ордера/fill для аудита.",
    details:
      "Хеши, batch id, ranks, raw open, timestamps. Источник истины — persisted facts, не сгенерированный текст.",
    relatedIds: ["decision_why", "decision_reason_code"],
  },
  sim_survivorship: {
    id: "sim_survivorship",
    kind: "term",
    title: "Survivorship и прочие лимиты",
    summary: "Текущая активная когорта инструментов может смещать историю «в пользу выживших».",
    details:
      "Universe current_active_instruments — fixed/current cohort. Плюс: нет дивидендного cash, IMOEX price-only, упрощённые bps, research ≠ trading.",
    limitations: [
      "Survivorship bias.",
      "Price return без дивидендов.",
      "Не брокерский P&L.",
    ],
    relatedIds: ["sim_oos", "sim_excess"],
  },
};

export const HELP_PAGES: Record<string, PageHelpContent> = {
  overview: {
    id: "overview",
    title: "Обзор",
    about: "Сводка здоровья платформы, рыночных данных и недавних процессов.",
    understand: [
      "Работают ли ключевые сервисы",
      "Есть ли свежие рыночные данные",
      "Какие процессы недавно выполнялись",
    ],
    metrics: ["data_quality"],
    interpret: [
      "Сначала смотрите статус сервисов и свежесть данных.",
      "Ошибки DQ важнее предупреждений.",
    ],
    limitations: ["Это operational overview, не торговый дашборд."],
  },
  market: {
    id: "market",
    title: "Рыночные данные",
    about: "Каталог инструментов, источники MOEX/ЦБ и состояние загрузок.",
    understand: [
      "Какие инструменты загружены",
      "Диапазон доступной истории",
      "Можно ли запустить update / backfill / DQ",
    ],
    metrics: ["last_price", "data_quality", "raw_candles"],
    interpret: [
      "Открывайте инструмент для графика и вкладок качества.",
      "Фильтры сужают universe, не меняют данные в БД.",
    ],
    limitations: ["UI показывает RAW-историю, не portfolio P&L."],
  },
  instrument: {
    id: "instrument",
    title: "Инструмент",
    about: "Карточка инструмента: обзор, котировки, загрузки, DQ, аналитика и technical.",
    understand: [
      "История RAW-цен и выбранный период",
      "Последние признаки Analytics",
      "Техническое состояние rules_v1",
    ],
    metrics: [
      "last_price",
      "raw_candles",
      "return_20d",
      "rsi14",
      "confidence",
      "technical_score",
    ],
    interpret: [
      "Вкладка «Котировки» — исследование периода по RAW close.",
      "Analytics и Technical — производные слои, не приказы.",
    ],
    limitations: [
      "Короткая история (T/YDEX и аналоги) ограничивает длинные пресеты.",
      "Не переключаемся на adjusted цены.",
    ],
  },
  analytics: {
    id: "analytics",
    title: "Аналитика",
    about: "Версионируемые производные признаки из рыночных данных (feature sets).",
    understand: [
      "Какой feature set активен",
      "Покрытие инструментов",
      "История расчётов признаков",
    ],
    metrics: ["return_1d", "return_5d", "return_20d", "volatility_20d", "feature_coverage"],
    interpret: [
      "Признаки — входы для моделей, не рекомендации.",
      "Mechanical V2 — отдельный набор; не активируется этим экраном.",
    ],
    limitations: ["UI не запускает ML-обучение."],
  },
  relations: {
    id: "relations",
    title: "Связи",
    about: "Статистическая структура рынка: корреляции и lead-lag.",
    understand: [
      "Какие пары сильнее связаны на окне",
      "Есть ли выраженный лаг",
      "Насколько snapshot валиден",
    ],
    metrics: ["relations_term", "pearson", "spearman", "best_lag"],
    interpret: [
      "Топ связей зависит от окна, фильтра |corr| и поиска.",
      "Pair explorer показывает профиль лагов выбранной пары.",
    ],
    limitations: [
      "Корреляция ≠ причинность.",
      "Не выдача BUY/SELL.",
    ],
  },
  technical: {
    id: "technical",
    title: "Технический анализ",
    about: "Rules_v1: score, direction и confidence по тренду, моментуму, RSI и объёму.",
    understand: [
      "Распределение бычьих/нейтральных/медвежьих состояний",
      "Сигналы по инструментам на as_of",
      "Качество и confidence",
    ],
    metrics: ["technical_score", "confidence", "rsi14", "sma20_distance", "atr14_pct", "return_20d"],
    interpret: [
      "Сортируйте по confidence осторожно: это не вероятность прибыли.",
      "Invalid / предупреждения важнее «красивого» score.",
    ],
    limitations: ["Не рекомендация к сделке.", "Не брокерский сигнал."],
  },
  workflows: {
    id: "workflows",
    title: "Процессы",
    about: "Фоновые задачи загрузки, DQ, analytics, relations и technical.",
    understand: ["Какие задачи бегут сейчас", "Где упал шаг", "Длительность и статус"],
    metrics: [],
    interpret: ["Открывайте процесс, чтобы увидеть timeline шагов."],
    limitations: ["Это журнал оркестрации, не бизнес-отчёт."],
  },
  system: {
    id: "system",
    title: "Система",
    about: "Здоровье сервисов, сведения о сборке и техническая диагностика.",
    understand: ["Доступность БД/Redis/worker", "События диагностики"],
    metrics: [],
    interpret: ["При деградации сначала смотрите сервисный статус, затем tech events."],
    limitations: ["Не заменяет мониторинг инфраструктуры вне Docker-стека."],
  },
  simulator: {
    id: "simulator",
    title: "Симуляции",
    about: "Список прогонов Historical Simulator V0: сегменты DEV OOS и HOLDOUT, издержки, метрики.",
    understand: [
      "Какие research-прогоны сохранены",
      "Разница сегментов и commission bps",
      "Куда перейти за кривой NAV и инспектором дня",
    ],
    metrics: ["sim_nav", "sim_cagr", "sim_max_drawdown", "sim_bps", "sim_oos", "sim_holdout"],
    interpret: [
      "HOLDOUT визуально отделён от DEV — это разные периоды оценки.",
      "Engineering PASS ≠ прибыльность.",
    ],
    limitations: [
      "Research dashboard, не live trading.",
      "Числа зависят от spec (bps, policy, capital).",
    ],
  },
  simulator_run: {
    id: "simulator_run",
    title: "Симуляция портфеля",
    about:
      "Дашборд одного прогона: NAV vs IMOEX, просадка, инспектор даты, fills provenance, cost sensitivity, DEV/HOLDOUT.",
    understand: [
      "Абсолютная доходность vs относительный результат в п.п.",
      "Поведение капитала на выбранном окне",
      "Фактические причины сделок без LLM",
      "Краткое объяснение → Подробнее → Технические детали",
    ],
    metrics: [
      "sim_nav",
      "sim_cagr",
      "sim_excess",
      "sim_max_drawdown",
      "sim_sharpe",
      "sim_turnover",
      "sim_commission",
      "sim_survivorship",
      "sim_oos",
      "sim_holdout",
      "sim_rebalance",
      "sim_next_open",
      "decision_why",
      "decision_pred_20d",
      "decision_rank",
    ],
    interpret: [
      "Отрицательная «Доходность портфеля» — убыток; положительный excess может быть при общем падении рынка.",
      "MIXED — research-контекст Candidate V0, отделён от engineering PASS.",
      "Клик по графику открывает day inspector.",
    ],
    limitations: [
      "Survivorship bias universe.",
      "Без дивидендов.",
      "IMOEX price index.",
      "Не разрешение на реальные деньги.",
    ],
  },
};

export function getMetricHelp(id: string): HelpEntry | undefined {
  return HELP_METRICS[id];
}

export function getPageHelp(id: string): PageHelpContent | undefined {
  return HELP_PAGES[id];
}

export function resolveHelpEntry(id: string): HelpEntry | undefined {
  return HELP_METRICS[id];
}
