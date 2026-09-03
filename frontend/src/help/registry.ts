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
      "Используется и в Analytics, и в Technical Agent. Считается на RAW-сериях; V2 mechanical adjustment — отдельный feature set, не этот экран по умолчанию.",
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
    summary: "coverage × agreement × quality — не вероятность прибыли.",
    details:
      "В Technical Agent V1: confidence = clip(coverage × agreement × quality_factor, 0, 1). Coverage — доля доступных факторов; agreement — согласованность знаков; quality — штраф за качество данных.",
    interpretation:
      "Высокий confidence значит «модель смогла согласованно оценить состояние», а не «сделка с высокой вероятностью успеха».",
    limitations: [
      "Не вероятность прибыли и не калиброванная вероятность направления.",
      "При price_discontinuity / invalid сигнал обнуляется.",
    ],
    relatedIds: ["technical_score", "rsi14"],
  },
  rsi14: {
    id: "rsi14",
    kind: "metric",
    title: "RSI14",
    summary: "Relative Strength Index за 14 торговых дней.",
    details:
      "Классический осциллятор моментума на дневных close. В rules_v1 участвует как фактор, а не как торговый триггер сам по себе.",
    interpretation: "Около 30/70 часто читают как зоны перепроданности/перекупленности — в ProjectAI это вход в score, не приказ.",
    limitations: ["На короткой истории может отсутствовать.", "Считается по RAW close."],
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
    summary: "Неизменяемые биржевые OHLCV из market.candles.",
    details:
      "ProjectAI хранит RAW exchange OHLCV. Сплиты и дивиденды не переписывают историю свечей в этом UI. Adjusted / total-return ряды — отдельные будущие представления.",
    limitations: ["Дивидендные гэпы видны как есть.", "Не переключаемся молча на adjusted."],
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
