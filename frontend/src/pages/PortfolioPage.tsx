import { FormEvent, useEffect, useRef, useState } from "react";
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
  const nameInputRef = useRef<HTMLInputElement>(null);

  function focusCreateForm() {
    const form = document.getElementById("new-portfolio");
    form?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => nameInputRef.current?.focus(), 50);
  }

  useEffect(() => {
    if (window.location.hash === "#new-portfolio") {
      focusCreateForm();
    }
  }, []);

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
          <p style={{ margin: "0 0 0.75rem" }}>
            Создайте первый портфель, добавьте деньги и активы — Kraken начнёт анализировать именно
            его. Можно создать несколько портфелей и переключаться между ними.
          </p>
          <button
            type="button"
            className="button"
            data-testid="create-first-portfolio-cta"
            onClick={focusCreateForm}
          >
            Создать первый портфель
          </button>
        </HeroCard>
      ) : (
        <div className="portfolio-hub-grid">
          {portfolios.map((p) => (
            <article
              key={p.id}
              className={`portfolio-card${selectedPortfolioId === p.id ? " is-selected" : ""}`}
            >
              <header className="portfolio-card-header">
                <strong className="portfolio-card-title">{p.name}</strong>
                {selectedPortfolioId === p.id ? (
                  <span className="badge badge-running">выбран</span>
                ) : null}
              </header>
              <p className="portfolio-card-meta">
                <span>{lifecycleLabel(p.lifecycle_state)}</span>
                <span>
                  Кэш {p.cash_rub} ₽ · активов {p.positions_count}
                </span>
              </p>
              <div className="portfolio-card-actions">
                <Link className="button" to={`/portfolio/${p.id}`}>
                  Открыть
                </Link>
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => void onRename(p.id, p.name)}
                >
                  Переименовать
                </button>
                <button
                  type="button"
                  className="button quiet-danger"
                  onClick={() => void onDelete(p.id, p.name)}
                >
                  Удалить
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <ExplanationCard title="Новый портфель" level={1}>
        <form
          id="new-portfolio"
          onSubmit={onCreate}
          style={{ display: "grid", gap: 8, maxWidth: 420 }}
          data-testid="new-portfolio-form"
        >
          <p className="muted" style={{ margin: 0 }}>
            После создания откроется режим настройки: кэш, поиск инструментов, позиции и
            себестоимость. Журнал учёта включается отдельно, когда состав готов.
          </p>
          <label>
            Название *
            <input
              ref={nameInputRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Основной"
              required
              maxLength={120}
              data-testid="new-portfolio-name"
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
          <button type="submit" className="btn btn-primary" disabled={busy} data-testid="new-portfolio-submit">
            {busy
              ? "Создание…"
              : portfolios.length === 0
                ? "Создать первый портфель"
                : "Создать"}
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
