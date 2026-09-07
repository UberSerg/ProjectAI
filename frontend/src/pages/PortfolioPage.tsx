import { Link } from "react-router-dom";
import { ExplanationCard, HeroCard, PageHeader } from "../components/Ui";

const links = [
  {
    to: "/portfolio/candidate",
    title: "Открыть кандидат портфеля",
    text: "Главный экран: конкретные тикеры, лоты, суммы, риски и отклонения.",
  },
  {
    to: "/investment-decision",
    title: "Инвестиционное решение",
    text: "Что делать с капиталом: акции / облигации / деньги и почему.",
  },
  {
    to: "/portfolio-risk",
    title: "Проверка риска",
    text: "Можно ли допустить инструмент и размер позиции в кандидат портфеля.",
  },
  {
    to: "/allocation",
    title: "Распределение капитала",
    text: "Подробный deep-link: research-allocation. В основной навигации не показан — смотрите через решение / кандидат.",
  },
  {
    to: "/bonds",
    title: "Облигации",
    text: "Подходит ли бумага: доходность, срок, кредит, ликвидность.",
  },
  {
    to: "/calibration",
    title: "Качество прогнозов",
    text: "Насколько можно доверять модели прямо сейчас.",
  },
];

export function PortfolioPage() {
  return (
    <section>
      <PageHeader
        title="Обзор портфеля (хаб)"
        description="Служебный хаб по deep-link. В основной навигации его нет — главный путь инвестора: кандидат портфеля."
        helpPageId="portfolio_hub"
      />
      <p className="page-purpose">
        Распределение капитала концептуально живёт внутри инвестиционного решения и кандидата; отдельный
        экран /allocation сохранён для подробного разбора.
      </p>

      <HeroCard
        eyebrow="Куда смотреть"
        headline="Сначала кандидат портфеля, потом детали"
      >
        <p style={{ margin: 0 }}>
          <Link to="/portfolio/candidate">Открыть кандидат портфеля</Link> — один экран с конкретным
          составом на 100 000 ₽. Остальные страницы объясняют, почему получился такой ответ.
        </p>
      </HeroCard>

      <div className="portfolio-hub-grid">
        {links.map((item) => (
          <Link key={item.to} className="hub-link" to={item.to}>
            <strong>{item.title}</strong>
            <span>{item.text}</span>
          </Link>
        ))}
      </div>

      <ExplanationCard title="Как читать этот раздел" level={1}>
        <ol className="plain-list">
          <li>Откройте «Кандидат портфеля» — увидите конкретный состав.</li>
          <li>Откройте «Инвестиционное решение» — увидите доли капитала.</li>
          <li>Проверьте «Проверку риска» — что блокирует или предупреждает.</li>
          <li>При сомнении по облигациям зайдите в «Облигации» и «Качество прогнозов».</li>
        </ol>
      </ExplanationCard>
    </section>
  );
}
