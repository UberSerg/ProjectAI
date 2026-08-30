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
  degraded: "С ограничениями",
  unknown: "Неизвестно",
  not_monitored: "Не контролируется",
  info: "Информация",
};

const WORKFLOW_TYPE: Record<string, string> = {
  MarketDataBackfill: "Загрузка истории котировок",
  MarketDataUpdate: "Обновление рыночных данных",
  DataQualityCheck: "Проверка качества данных",
};

const WORKFLOW_STEP: Record<string, string> = {
  "Resolve instruments": "Подготовка инструментов",
  "Download MOEX": "Получение данных MOEX",
  "Download CBR": "Получение данных ЦБ РФ",
  "Save RAW": "Сохранение RAW",
  "Normalize / Persist": "Нормализация и запись в БД",
  "Run Data Quality": "Проверка качества",
  Finish: "Завершение",
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

function lookup(map: Record<string, string>, value?: string | null): string {
  if (!value) return "—";
  return map[value] ?? map[value.toLowerCase()] ?? value;
}

export const labels = {
  nav: {
    overview: "Обзор",
    market: "Рыночные данные",
    analytics: "Аналитика",
    recommendations: "Рекомендации",
    models: "Модели",
    decisionMemory: "Память решений",
    trading: "Торговля",
    portfolio: "Портфель",
    systemGroup: "Система",
    workflows: "Процессы",
    system: "Система",
    soon: "Скоро",
  },
  actions: {
    update: "Обновить данные",
    backfill: "Загрузить историю",
    dataQuality: "Проверить качество",
    resetFilters: "Сбросить фильтры",
    retry: "Повторить",
    cancel: "Отмена",
    start: "Запустить",
    openWorkflow: "Открыть процесс",
  },
  assetClass: (value?: string | null) => lookup(ASSET_CLASS, value),
  status: (value?: string | null) => lookup(STATUS, value?.toLowerCase()),
  workflowType: (value?: string | null) => lookup(WORKFLOW_TYPE, value),
  workflowStep: (value?: string | null) => lookup(WORKFLOW_STEP, value),
  issueType: (value?: string | null) => lookup(ISSUE_TYPE, value),
  service: (value?: string | null) => lookup(SERVICE, value),
  dataFreshness: (last?: string | null): string => {
    if (!last) return "Нет данных";
    const days = Math.floor((Date.now() - new Date(last).getTime()) / 86_400_000);
    if (Number.isNaN(days)) return "—";
    if (days <= 3) return "Актуальны";
    if (days <= 10) return "Устаревают";
    return "Устарели";
  },
};
