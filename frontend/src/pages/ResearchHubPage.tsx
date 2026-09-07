import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getShadowLive, type ShadowLiveResponse } from "../api/shadow";
import { PageHeader } from "../components/Ui";
import {
  deriveLiveExperimentStatus,
  liveExperimentStatusLabel,
  pickPortfolioA,
} from "../features/shadow/helpers";
import { labels } from "../utils/labels";

const groups = [
  {
    title: "Проверка моделей",
    cards: [
      {
        to: "/calibration",
        title: labels.nav.calibration,
        what: "Сколько зрелых прогнозов уже есть и насколько им можно доверять.",
        why: "Без калибровки Kraken не должен уверенно наращивать долю акций.",
        forUser: "Да — если хотите понять, почему капитал осторожен.",
      },
      {
        to: "/shadow",
        title: labels.nav.liveExperiment,
        what: "Живое наблюдение решений после запуска эксперимента, без пересчёта прошлого.",
        why: "Проверяет, как пайплайн ведёт себя на новых данных.",
        forUser: "Обычно достаточно заглянуть иногда; не главный экран инвестора.",
        liveKey: "shadow" as const,
      },
    ],
  },
  {
    title: "Проверка стратегий",
    cards: [
      {
        to: "/simulator",
        title: labels.nav.historicalSimulations,
        what: "Исторические прогоны политик на прошлых периодах (walk-forward / holdout).",
        why: "Показывает, как идея вела себя раньше — без обещания будущего.",
        forUser: "Полезно при разборе research; не заменяет кандидат портфеля.",
      },
      {
        to: "/research",
        title: labels.nav.researchLab,
        what: "Лаборатория экспериментов, сравнение и диагностика моделей.",
        why: "Для экспертов, которые разбирают edge и ограничения.",
        forUser: "Нет для обычного просмотра портфеля — только research.",
      },
    ],
  },
  {
    title: "Внутренние данные",
    cards: [
      {
        to: "/research/advanced",
        title: labels.nav.advancedAnalytics,
        what: "Аналитика признаков, технические сигналы и связи рынка.",
        why: "Сырьё и производные слои для моделей, не инвестиционный совет.",
        forUser: "Нет — это экспертный слой. Основной путь: портфель и рынок.",
      },
    ],
  },
];

function useShadowLiveStatus(): string | null {
  const [live, setLive] = useState<ShadowLiveResponse | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getShadowLive(controller.signal)
      .then(setLive)
      .catch(() => setLive(null));
    return () => controller.abort();
  }, []);
  if (!live) return null;
  const primary = pickPortfolioA(live.portfolios) ?? live.portfolios[0];
  if (!primary) return "ещё не инициализирован";
  const status = deriveLiveExperimentStatus({
    live,
    primary,
    hasForward: true,
  });
  return liveExperimentStatusLabel(status);
}

export function ResearchHubPage() {
  const shadowStatus = useShadowLiveStatus();

  return (
    <section className="research-hub-page" data-testid="research-hub-page">
      <PageHeader
        title={labels.nav.researchHub}
        description="Здесь собраны проверки моделей и стратегий. Обычному инвестору чаще нужен кандидат портфеля; этот раздел — для доверия и разбора."
        helpPageId="research_hub"
      />
      <p className="page-purpose">
        Не путайте research-экраны с торговлей: здесь нет брокера и нет кнопки «купить».
      </p>

      {groups.map((group) => (
        <div key={group.title} className="card">
          <h2>{group.title}</h2>
          <div className="hub-card-grid">
            {group.cards.map((card) => (
              <Link key={card.to} to={card.to} className="hub-link research-hub-card">
                <strong>{card.title}</strong>
                {"liveKey" in card && card.liveKey === "shadow" && shadowStatus ? (
                  <span className="muted" data-testid="research-hub-shadow-status">
                    Сейчас: {shadowStatus}
                  </span>
                ) : null}
                <span>
                  <em>Что это:</em> {card.what}
                </span>
                <span>
                  <em>Зачем:</em> {card.why}
                </span>
                <span>
                  <em>Нужно ли обычному пользователю:</em> {card.forUser}
                </span>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
