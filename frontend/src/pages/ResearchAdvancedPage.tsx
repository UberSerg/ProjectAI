import { Link } from "react-router-dom";
import { PageHeader } from "../components/Ui";
import { labels } from "../utils/labels";

const expertLinks = [
  {
    to: "/analytics",
    title: labels.nav.analytics,
    text: "Версионируемые признаки и покрытие feature sets — входы для моделей.",
  },
  {
    to: "/technical",
    title: labels.nav.technical,
    text: "Rules-based технические сигналы: score, направление, confidence.",
  },
  {
    to: "/relations",
    title: labels.nav.relations,
    text: "Статистические связи инструментов: корреляции и lead-lag.",
  },
];

export function ResearchAdvancedPage() {
  return (
    <section className="research-advanced-page" data-testid="research-advanced-page">
      <PageHeader
        title={labels.nav.advancedAnalytics}
        description="Экспертный слой внутренних данных. Не основной путь инвестора — сюда заходят, чтобы разобрать сырьё моделей."
        helpPageId="research_advanced"
      />
      <p className="page-purpose">
        Эти экраны не выдают инвестиционное решение. Для капитала смотрите{" "}
        <Link to="/portfolio/candidate">кандидат портфеля</Link> и{" "}
        <Link to="/investment-decision">инвестиционное решение</Link>. Обзор исследований —{" "}
        <Link to="/research-hub">{labels.nav.researchHub.toLowerCase()}</Link>.
      </p>

      <div className="portfolio-hub-grid">
        {expertLinks.map((item) => (
          <Link key={item.to} className="hub-link" to={item.to}>
            <strong>{item.title}</strong>
            <span>{item.text}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
