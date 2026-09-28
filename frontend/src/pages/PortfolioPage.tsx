import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  createPersonalPortfolio,
  deletePersonalPortfolio,
  patchPersonalPortfolio,
} from "../api/personalPortfolios";
import { ExplanationCard, HeroCard, PageHeader, PageState } from "../components/Ui";
import { usePortfolioContext } from "../portfolio/PortfolioContext";

function lifecycleLabel(state: string | undefined): string {
  if (state === "ACTIVE") return "Учёт включён";
  return "Настройка";
}

export function PortfolioPage() {
  const navigate = useNavigate();
  const { portfolios, selectedPortfolioId, selectPortfolio, refreshList, loading, error } =
    usePortfolioContext();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const summary = await createPersonalPortfolio({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      await refreshList();
      selectPortfolio(summary.portfolio.id);
      setName("");
      setDescription("");
      navigate(`/portfolio/${summary.portfolio.id}`);
    } catch (reason) {
      setFormError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function onRename(id: number, current: string) {
    const next = window.prompt("Новое название портфеля", current);
    if (!next || !next.trim()) return;
    try {
      await patchPersonalPortfolio(id, { name: next.trim() });
      await refreshList();
    } catch (reason) {
      window.alert(errorMessage(reason));
    }
  }

  async function onDelete(id: number, label: string) {
    const ok = window.confirm(
      `Удалить портфель «${label}»?\nУдаление нельзя отменить. Остальные портфели не изменятся.`,
    );
    if (!ok) return;
    const ok2 = window.confirm(`Подтвердите удаление портфеля «${label}».`);
    if (!ok2) return;
    try {
      await deletePersonalPortfolio(id);
      const items = await refreshList();
      if (selectedPortfolioId === id) {
        const next = items[0]?.id ?? null;
        selectPortfolio(next);
        navigate(next != null ? `/portfolio/${next}` : "/portfolio");
      }
    } catch (reason) {
      window.alert(errorMessage(reason));
    }
  }

  if (loading && portfolios.length === 0) {
    return <PageState kind="loading" title="Портфели" />;
  }

  return (
    <section>
      <PageHeader
        title="Портфели"
        description="Несколько независимых портфелей: выберите один — Kraken анализирует только его."
        helpPageId="portfolio_hub"
      />

      {error && <p className="error-text">{error}</p>}

      {portfolios.length === 0 ? (
        <HeroCard eyebrow="Начало" headline="У вас пока нет портфелей">
          <p style={{ margin: 0 }}>
            Создайте первый портфель, добавьте деньги и активы — Kraken начнёт анализировать именно
            его. Можно создать несколько портфелей и переключаться между ними.
          </p>
        </HeroCard>
      ) : (
        <div className="portfolio-hub-grid">
          {portfolios.map((p) => (
            <div key={p.id} className="hub-link" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <strong>
                {p.name}
                {selectedPortfolioId === p.id ? " · выбран" : ""}
              </strong>
              <span>{lifecycleLabel(p.lifecycle_state)}</span>
              <span>
                Кэш {p.cash_rub} ₽ · активов {p.positions_count}
              </span>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Link className="btn btn-primary" to={`/portfolio/${p.id}`}>
                  Открыть
                </Link>
                <button type="button" className="btn" onClick={() => void onRename(p.id, p.name)}>
                  Переименовать
                </button>
                <button type="button" className="btn" onClick={() => void onDelete(p.id, p.name)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ExplanationCard title="Новый портфель" level={1}>
        <form onSubmit={onCreate} style={{ display: "grid", gap: 8, maxWidth: 420 }}>
          <label>
            Название *
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Основной"
              required
              maxLength={120}
            />
          </label>
          <label>
            Описание
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Дивидендный / ОФЗ / …"
              maxLength={500}
            />
          </label>
          {formError && <div className="error-text">{formError}</div>}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Создание…" : "Создать"}
          </button>
        </form>
      </ExplanationCard>

      <p className="page-purpose">
        Кандидат Kraken и Shadow остаются отдельными контурами — это не пользовательские портфели.
      </p>
      <p>
        <Link to="/portfolio/candidate">Собрать портфель (кандидат модели)</Link>
      </p>
    </section>
  );
}
