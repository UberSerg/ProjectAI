import type { EvidenceLimitation } from "../../api/researchEvidence";

export const RESEARCH_ONLY_BADGE = "RESEARCH ONLY";
export const ENGINE_TITLE = "Research Evidence Engine V1";
export const PROSPECTIVE_DIVIDER = "Проспективные наблюдения";
export const ECONOMICS_DISCLAIMER = "Историческая OOS симуляция, не фактический счёт";
export const NO_DATA_LABEL = "нет данных";
export const PRIMARY_CONTRACT_LABEL = "PRIMARY RESEARCH CONTRACT";
export const LAUNCH_CANONICAL_LABEL = "Запустить каноническое исследование";
export const EXACT_RERUN_LABEL = "Точный пересчёт с теми же семантиками";

export const OOS_VARIANT_ORDER = ["base", "fund", "events", "full_v4"] as const;
export const OOS_VARIANT_LABELS: Record<(typeof OOS_VARIANT_ORDER)[number], string> = {
  base: "BASE",
  fund: "FUND",
  events: "EVENTS",
  full_v4: "V4 FULL",
};

export const PRIMARY_REBALANCE_SESSIONS = 20;
export const PRIMARY_SELECTION_TOP_PCT = 20;
export const PRIMARY_COST_BPS = 30;
export const ROBUSTNESS_COST_BPS = [0, 10, 30, 50] as const;
export const ROBUSTNESS_REBALANCE = [10, 20, 40] as const;
export const ROBUSTNESS_SELECTION = [10, 20, 30] as const;

export const ABLATION_VARIANT_ORDER = ["base", "fund", "events", "full_v4"] as const;

export const ABLATION_VARIANT_LABELS: Record<(typeof ABLATION_VARIANT_ORDER)[number], string> = {
  base: "Base",
  fund: "+Fund",
  events: "+Events",
  full_v4: "Full V4",
};

export const ECONOMICS_SCENARIO_ORDER = ["gross", "net_10bps", "net_30bps", "net_50bps"] as const;

export const ECONOMICS_SCENARIO_LABELS: Record<(typeof ECONOMICS_SCENARIO_ORDER)[number], string> = {
  gross: "Gross",
  net_10bps: "Net 10 bps",
  net_30bps: "Net 30 bps",
  net_50bps: "Net 50 bps",
};

export const ECONOMICS_SCENARIO_BPS: Record<(typeof ECONOMICS_SCENARIO_ORDER)[number], number | null> =
  {
    gross: 0,
    net_10bps: 10,
    net_30bps: 30,
    net_50bps: 50,
  };

/** Always shown, even if the API omits them. */
export const REQUIRED_LIMITATIONS: EvidenceLimitation[] = [
  {
    code: "TR_INCOMPLETE",
    title: "Total Return неполный",
    detail: "TR incomplete: полный ряд total return пока недоступен, оценка идёт по PRICE_RETURN.",
  },
  {
    code: "DIVIDENDS_EXCLUDED",
    title: "Дивиденды исключены",
    detail: "Dividends excluded: дивидендные выплаты не входят в сырой ряд и в эту симуляцию.",
  },
  {
    code: "BANK_FI_PARTIAL",
    title: "Банки / FI покрыты частично",
    detail: "Bank/FI partial: фундаментал банков и фининструментов покрыт не полностью.",
  },
  {
    code: "DELISTED_PARTIAL",
    title: "Делистинг покрыт частично",
    detail: "Delisted partial: исключённые с торгов бумаги представлены неполно.",
  },
  {
    code: "CURRENT_ONLY_WEAKER",
    title: "CURRENT_ONLY слабее полного PIT-ряда",
    detail: "CURRENT_ONLY weaker: срез «только текущее» слабее полной point-in-time истории.",
  },
  {
    code: "FRACTIONAL_SIZING",
    title: "Дробное sizing в симуляции",
    detail: "Fractional sizing: позиции могут быть дробными — это допущение лаборатории, не брокер.",
  },
  {
    code: "ASSUMED_COSTS",
    title: "Издержки заданы допущением",
    detail: "Assumed costs: комиссии 10/30/50 bps — сценарии, не фактический тариф счёта.",
  },
  {
    code: "NO_AUTO_CANDIDATE_PROMOTION",
    title: "Нет автоматического продвижения Candidate",
    detail:
      "No auto Candidate promotion: этот экран не повышает Candidate и не включает торговлю.",
  },
];

export const DEFAULT_CHECKING = [
  "Совпадает ли Dataset V3 и V4 по identity выборки и есть ли PIT-нарушения (ожидаем 0).",
  "Есть ли устойчивый исторический OOS-сигнал у Regression и Ranker по отдельности (Rank IC, spread, n, годы/фолды).",
  "Что добавляют фундамент и события в абляции Base / +Fund / +Events / Full V4 — без выбора «победителя».",
  "Как выглядит историческая OOS-симуляция PRICE_RETURN при условных издержках (не фактический счёт).",
  "Что видно в проспективных наблюдениях — отдельно от исторических метрик.",
  "Какие ограничения данных нельзя игнорировать перед любым выводом.",
];
