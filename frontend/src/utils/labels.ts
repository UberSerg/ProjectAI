/** Централизованные UI-подписи (без i18n-библиотеки). */

const ASSET_CLASS: Record<string, string> = {
  equity: "Акция",
  stock: "Акция",
  index: "Индекс",
  currency: "Валюта",
  fx: "Валюта",
  rate: "Ставка",
  bond: "Облигация",
};

const STATUS: Record<string, string> = {
  active: "Активен",
  inactive: "Неактивен",
  enabled: "Включено",
  disabled: "Выключено",
  success: "Успешно",
  succeeded: "Успешно",
  completed: "Завершено",
  warning: "Предупреждение",
  error: "Ошибка",
  failed: "Ошибка",
  running: "Выполняется",
  pending: "Ожидает",
  ok: "Работает",
  healthy: "Работает",
  pass: "PASS",
  degraded: "С ограничениями",
  unknown: "Неизвестно",
  not_monitored: "Не контролируется",
  info: "Информация",
  not_ready: "Не готово",
  partial: "Частично",
  deferred: "Отложено",
  good: "Хорошо",
};

const WORKFLOW_TYPE: Record<string, string> = {
  MarketDataBackfill: "Загрузка истории котировок",
  MarketDataUpdate: "Обновление рыночных данных",
  DataQualityCheck: "Проверка качества данных",
  FeatureBackfill: "Пересчёт признаков (история)",
  FeatureUpdate: "Обновление признаков",
  RelationsComputeLatest: "Расчёт связей (latest)",
  RelationsBackfill: "Пересчёт связей (история)",
  TechnicalBackfill: "Пересчёт технического анализа (история)",
  TechnicalUpdate: "Обновление технического анализа",
  DAILY_RESEARCH_CYCLE_V0: "Ежедневный исследовательский цикл",
};

const WORKFLOW_STEP: Record<string, string> = {
  "Resolve instruments": "Подготовка инструментов",
  "Download MOEX": "Получение данных MOEX",
  "Download CBR": "Получение данных ЦБ РФ",
  "Save RAW": "Сохранение RAW",
  "Normalize / Persist": "Нормализация и запись в БД",
  "Run Data Quality": "Проверка качества",
  Finish: "Завершение",
  "Resolve feature set": "Подготовка набора признаков",
  "Resolve universe": "Подготовка universe",
  "Load source market data": "Загрузка рыночных данных",
  "Load source quality issues": "Загрузка quality issues",
  "Calculate instrument features": "Расчёт признаков инструментов",
  "Calculate series features": "Расчёт признаков series",
  "Persist batches": "Сохранение результатов",
  "Run feature quality summary": "Сводка качества признаков",
  "Resolve relation set": "Подготовка набора связей",
  "Resolve / seed inputs": "Подготовка relation inputs",
  "Resolve as-of dates": "Определение as_of дат",
  "Load feature matrix": "Загрузка матрицы признаков",
  "Calculate relations": "Расчёт связей",
  "Persist snapshots": "Сохранение snapshots",
  "Run quality summary": "Сводка качества связей",
  "Resolve model": "Подготовка модели",
  "Resolve feature sets": "Подготовка наборов признаков",
  "Load source market/basic analytics": "Загрузка рынка и базовой аналитики",
  "Calculate technical features": "Расчёт технических признаков",
  "Persist technical features": "Сохранение технических признаков",
  "Build frozen model inputs": "Сборка входов модели",
  "Evaluate rules model": "Оценка rules-модели",
  "Persist technical signals": "Сохранение технических сигналов",
};

const DIRECTION: Record<string, string> = {
  bullish: "Бычье",
  neutral: "Нейтральное",
  bearish: "Медвежье",
};

const ISSUE_TYPE: Record<string, string> = {
  abnormal_price_jump: "Резкое изменение цены",
  missing_recent_data: "Нет свежих данных",
  suspicious_empty_response: "Пустой ответ источника",
  invalid_ohlc: "Некорректные OHLC",
  negative_volume: "Отрицательный объём",
  missing_instrument_mapping: "Нет привязки к источнику",
  duplicate_candle: "Дубликат свечи",
  missing_trading_days_in_range: "Пропуски торговых дней",
  source_lag: "Отставание источника",
};

const SERVICE: Record<string, string> = {
  core_db: "Основная БД",
  core_database: "Основная БД",
  memory_db: "База памяти",
  memory_database: "База памяти",
  redis: "Redis",
  worker: "Worker",
  scheduler: "Scheduler",
  backend: "Backend",
};

/** Shadow open-execution pending reason codes (display only). */
const SHADOW_PENDING_REASON: Record<string, string> = {
  ELIGIBLE: "Готов к исполнению на OPEN",
  NEXT_SESSION_NOT_STARTED: "Следующая сессия ещё не началась",
  WAITING_NEXT_SESSION: "Ждём следующую торговую сессию",
  OPEN_PRICE_NOT_AVAILABLE: "Цена открытия ещё не доступна",
  ORDER_CREATED_AFTER_OPEN: "Ордер создан после открытия сессии",
  QUOTE_STALE: "Котировка устарела",
  QUOTE_UNAVAILABLE: "Котировка недоступна",
  MARKET_CLOSED: "Рынок закрыт",
  NON_TRADING_DAY: "Неторговый день",
  NO_TRADES: "Сделок по инструменту ещё не было",
  MIN_EXECUTION_DATE_NOT_REACHED: "Ещё рано для исполнения (min execution date)",
  INSUFFICIENT_CASH: "Недостаточно денег в виртуальном портфеле",
  ALREADY_FILLED: "Уже исполнен",
  NO_POSITION_TO_SELL: "Нет позиции для продажи",
  FILLED: "Исполнен",
};

const QUOTE_FRESHNESS: Record<string, string> = {
  LIVE: "Актуальная",
  DELAYED: "С задержкой",
  STALE: "Устарела",
  SESSION_NOT_STARTED: "Сессия не началась",
  NO_TRADES: "Нет сделок",
  MARKET_CLOSED: "Рынок закрыт",
  UNAVAILABLE: "Недоступна",
};

const MARKET_SESSION: Record<string, string> = {
  PREOPEN: "Перед открытием",
  OPEN: "Сессия открыта",
  CLOSED: "Сессия закрыта",
  NON_TRADING_DAY: "Неторговый день",
  UNKNOWN: "Статус неизвестен",
};

function lookup(map: Record<string, string>, value?: string | null): string {
  if (!value) return "—";
  return map[value] ?? map[value.toLowerCase()] ?? value;
}

export const labels = {
  nav: {
    overview: "Обзор",
    market: "Рыночные данные",
    quotes: "Котировки",
    analytics: "Аналитика",
    relations: "Связи рынка",
    technical: "Технические сигналы",
    fundamentals: "Фундаментал и события",
    fundamentalsShort: "Компании",
    companies: "Компании",
    bonds: "Облигации",
    allocation: "Распределение",
    investmentDecision: "Инвестиционное решение",
    calibration: "Качество прогнозов",
    portfolioRisk: "Проверка риска",
    recommendations: "Рекомендации",
    models: "Модели",
    decisionMemory: "Память решений",
    trading: "Торговля",
    simulations: "Симуляции",
    historicalSimulations: "Исторические симуляции",
    liveExperiment: "Живой эксперимент",
    lab: "Лаборатория",
    researchLab: "Лаборатория исследований",
    researchHub: "Обзор исследований",
    advancedAnalytics: "Расширенная аналитика",
    portfolio: "Портфель",
    portfolioHub: "Обзор портфеля",
    portfolioCandidate: "Кандидат портфеля",
    portfolioGroup: "Портфель",
    marketGroup: "Рынок",
    researchGroup: "Исследования",
    systemGroup: "Система",
    workflows: "Процессы",
    system: "Система",
    soon: "Скоро",
  },
  actions: {
    update: "Обновить данные",
    backfill: "Загрузить историю",
    dataQuality: "Проверить качество",
    updateFeatures: "Обновить признаки",
    backfillFeatures: "Пересчитать историю",
    computeRelations: "Рассчитать связи",
    backfillRelations: "Backfill связей",
    updateTechnical: "Обновить",
    backfillTechnical: "Backfill",
    resetFilters: "Сбросить фильтры",
    retry: "Повторить",
    cancel: "Отмена",
    start: "Запустить",
    openWorkflow: "Открыть процесс",
  },
  tooltips: {
    confidence: "Уверенность не вероятность",
  },
  assetClass: (value?: string | null) => lookup(ASSET_CLASS, value),
  status: (value?: string | null) => lookup(STATUS, value?.toLowerCase()),
  workflowType: (value?: string | null) => lookup(WORKFLOW_TYPE, value),
  workflowStep: (value?: string | null) => lookup(WORKFLOW_STEP, value),
  issueType: (value?: string | null) => lookup(ISSUE_TYPE, value),
  service: (value?: string | null) => lookup(SERVICE, value),
  direction: (value?: string | null) => lookup(DIRECTION, value?.toLowerCase()),
  shadowPendingReason: (value?: string | null) => lookup(SHADOW_PENDING_REASON, value?.toUpperCase()),
  quoteFreshness: (value?: string | null) => lookup(QUOTE_FRESHNESS, value?.toUpperCase()),
  marketSession: (value?: string | null) => lookup(MARKET_SESSION, value?.toUpperCase()),
  dataFreshness: (last?: string | null): string => {
    if (!last) return "Нет данных";
    const days = Math.floor((Date.now() - new Date(last).getTime()) / 86_400_000);
    if (Number.isNaN(days)) return "—";
    if (days <= 3) return "Актуальны";
    if (days <= 10) return "Устаревают";
    return "Устарели";
  },
};
