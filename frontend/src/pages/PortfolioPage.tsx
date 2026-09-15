import { Link } from "react-router-dom";
import { ExplanationCard, HeroCard, PageHeader } from "../components/Ui";

const links = [
  {
    to: "/portfolio/mine",
    title: "Мой портфель",
    text: "Ручной снимок: позиции, оценка, сравнение с кандидатом Kraken и advisory-ребаланс.",
  },
  {
    to: "/portfolio/candidate",
    title: "Собрать портфель",
    text: "Главный сценарий: введите сумму — Kraken покажет lot-aware research-портфель.",
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
    to: "/instruments",
    title: "Каталог инструментов",
    text: "MOEX Instrument Master: поиск, support level и покрытие Kraken.",
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
        description="Служебный хаб: мой портфель, кандидат Kraken, решение и риск."
        helpPageId="portfolio_hub"
      />
      <p className="page-purpose">
        «Мой портфель» — ваш ручной снимок. «Собрать портфель» — ответ Kraken. Это разные экраны;
        брокер не подключается.
      </p>

      <HeroCard eyebrow="Куда смотреть" headline="Сначала мой портфель или кандидат Kraken">
        <p style={{ margin: 0 }}>
          <Link to="/portfolio/mine">Мой портфель</Link> — что у вас сейчас.{" "}
          <Link to="/portfolio/candidate?capital=100000">Собрать портфель</Link> — что предлагает
          Kraken на ваш капитал.
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
          <li>Откройте «Мой портфель» — ручной состав и оценка.</li>
          <li>Откройте «Собрать портфель» — research-состав Kraken на вашу сумму.</li>
          <li>Сравните на вкладке «Сравнение с Kraken» в моём портфеле.</li>
          <li>Проверьте «Инвестиционное решение» и «Проверку риска».</li>
        </ol>
      </ExplanationCard>
    </section>
  );
}
