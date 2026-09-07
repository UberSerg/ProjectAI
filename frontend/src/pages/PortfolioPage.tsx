import { Link } from "react-router-dom";
import { ExplanationCard, HeroCard, PageHeader } from "../components/Ui";

const links = [
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
    text: "Как считается research-allocation до risk gate.",
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
  {
    to: "/shadow",
    title: "Живой эксперимент",
    text: "Проверка идей «как будто» без реальных денег.",
  },
];

export function PortfolioPage() {
  return (
    <section>
      <PageHeader
        title="Портфель"
        description="Исследовательский контур: решение → риск → кандидат. Без брокера и без реальных денег."
        helpPageId="allocation"
      />

      <HeroCard
        eyebrow="Куда смотреть"
        headline="Сначала ответ Kraken, потом детали"
      >
        <p style={{ margin: 0 }}>
          Портфель здесь — не брокерский счёт. Это понятный путь: что предлагает система, почему, и
          какие ограничения стоят перед кандидатом на 100 000 ₽.
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
          <li>Откройте «Инвестиционное решение» — увидите доли капитала.</li>
          <li>Проверьте «Проверку риска» — что блокирует или предупреждает.</li>
          <li>При сомнении по облигациям зайдите в «Облигации» и «Качество прогнозов».</li>
        </ol>
      </ExplanationCard>
    </section>
  );
}
