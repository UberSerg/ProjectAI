import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getHurdle, type HurdleQuote } from "../../api/investment";
import { MetricHelp } from "../../help";

export function CbrHurdleBlock() {
  const [quote, setQuote] = useState<HurdleQuote | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHurdle(controller.signal).then(setQuote).catch(() => setQuote(null));
    return () => controller.abort();
  }, []);

  return (
    <div className="card" data-testid="cbr-hurdle-comparison">
      <h3>
        Strategy vs IMOEX vs CBR Hurdle <MetricHelp metricId="cbr_hurdle" />
      </h3>
      <p>
        <strong>Обогнал ли Kraken порог ключевой ставки?</strong>
      </p>
      <p className="muted">
        {quote?.annual_rate == null
          ? "INCONCLUSIVE — ключевая ставка или сопоставимый период недоступны."
          : `Текущий ориентир: ${(quote.annual_rate * 100).toFixed(2)}% годовых; verdict рассчитывается по результату симуляции за тот же период.`}
      </p>
      <p>
        Сравнить research-политики Equity / Fixed Income / Cash / Hurdle Gate:{" "}
        <Link to="/allocation">Распределение капитала</Link>
      </p>
    </div>
  );
}
