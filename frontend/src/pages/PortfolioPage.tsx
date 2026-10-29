import { FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  createPersonalPortfolio,
  deletePersonalPortfolio,
  getHubValuations,
  patchPersonalPortfolio,
  type HubValuationCard,
  type PortfolioCard,
} from "../api/personalPortfolios";
import { ExplanationCard, HeroCard, PageHeader, PageState } from "../components/Ui";
import { usePortfolioContext } from "../portfolio/PortfolioContext";

function lifecycleLabel(state: string | undefined): string {
  if (state === "ACTIVE") return "Учёт включён";
  return "Настройка";
}

/** RUB with kopecks — "3.340000" → "3,34 ₽", never "3 340 ₽". */
function formatRub(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ₽`;
}

function formatAsOf(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) {
    // Already a calendar date string YYYY-MM-DD
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (m) return `${m[3]}.${m[2]}.${m[1]}`;
    return iso;
  }
  return d.toLocaleDateString("ru-RU");
}

type CardValuationState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: HubValuationCard };

function PortfolioHubCard({
  portfolio,
  selected,
  valuation,
  onRename,
  onDelete,
}: {
  portfolio: PortfolioCard;
  selected: boolean;
  valuation: CardValuationState | undefined;
  onRename: () => void;
  onDelete: () => void;
}) {
  const v = valuation?.status === "ready" ? valuation.data : null;
  const loading = !valuation || valuation.status === "loading";
  const err = valuation?.status === "error" ? valuation.message : null;

  let totalBlock: ReactNode;
  if (loading) {
    totalBlock = (
      <p className="portfolio-card-total muted" data-testid={`hub-total-${portfolio.id}`}>
        Общая стоимость: …
      </p>
    );
  } else if (err) {
    totalBlock = (
      <p className="portfolio-card-total muted" data-testid={`hub-total-${portfolio.id}`}>
        Общая стоимость временно недоступна
      </p>
    );
  } else if (v?.valuation_complete && v.total_nav_rub != null) {
    totalBlock = (
      <p className="portfolio-card-total" data-testid={`hub-total-${portfolio.id}`}>
        Общая стоимость: <strong>{formatRub(v.total_nav_rub)}</strong>
      </p>
    );
  } else if (v?.valuation_unavailable) {
    totalBlock = (
      <div data-testid={`hub-total-${portfolio.id}`}>
        <p className="portfolio-card-total">Общая стоимость недоступна</p>
        <p className="muted portfolio-card-warn">Нет рыночных цен по открытым позициям.</p>
      </div>
    );
  } else if (v?.valuation_partial) {
    totalBlock = (
      <div data-testid={`hub-total-${portfolio.id}`}>
        <p className="portfolio-card-total">Общая стоимость недоступна</p>
        <p className="muted">
          Оценённая часть: <strong>{formatRub(v.known_nav_rub)}</strong>
        </p>
        <p className="muted portfolio-card-warn">
          {v.valuation_label ||
            `Цены части активов отсутствуют (${v.missing_price_count}).`}
        </p>
      </div>
    );
  } else {
    totalBlock = (
      <p className="portfolio-card-total muted" data-testid={`hub-total-${portfolio.id}`}>
        Общая стоимость недоступна
      </p>
    );
  }

  const cash = v?.cash_rub ?? portfolio.cash_rub;
  const securities = v?.securities_value_rub;
  const positions = v?.positions_count ?? portfolio.positions_count;
  const asOf =
    formatAsOf(v?.valuation_as_of) ||
    formatAsOf(v?.valuation_to) ||
    null;

  return (
    <article
      className={`portfolio-card${selected ? " is-selected" : ""}`}
      data-testid={`portfolio-hub-card-${portfolio.id}`}
    >
      <header className="portfolio-card-header">
        <strong className="portfolio-card-title">{portfolio.name}</strong>
        {selected ? <span className="badge badge-running">выбран</span> : null}
      </header>
      {totalBlock}
      <dl className="portfolio-card-metrics">
        <div>
          <dt>Свободные деньги</dt>
          <dd data-testid={`hub-cash-${portfolio.id}`}>{formatRub(cash)}</dd>
        </div>
        <div>
          <dt>Стоимость активов</dt>
          <dd data-testid={`hub-securities-${portfolio.id}`}>
            {loading
              ? "…"
              : err
                ? "Оценка недоступна"
                : securities == null
                  ? "—"
                  : formatRub(securities)}
          </dd>
        </div>
        <div>
          <dt>Позиций</dt>
          <dd data-testid={`hub-positions-${portfolio.id}`}>{positions}</dd>
        </div>
        <div>
          <dt>Статус</dt>
          <dd>{lifecycleLabel(portfolio.lifecycle_state)}</dd>
        </div>
        {asOf ? (
          <div>
            <dt>Оценка на</dt>
            <dd data-testid={`hub-asof-${portfolio.id}`}>{asOf}</dd>
          </div>
        ) : null}
      </dl>
      {err ? (
        <p className="error-text" data-testid={`hub-val-error-${portfolio.id}`}>
          Оценка: {err}
        </p>
      ) : null}
      <div className="portfolio-card-actions">
        <Link className="button" to={`/portfolio/${portfolio.id}`}>
          Открыть
        </Link>
        <button type="button" className="button secondary" onClick={onRename}>
          Переименовать
        </button>
        <button type="button" className="button quiet-danger" onClick={onDelete}>
          Удалить
        </button>
      </div>
    </article>
  );
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
  const [valuations, setValuations] = useState<Record<number, CardValuationState>>({});
  const valRequestRef = useRef(0);

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

  useEffect(() => {
    if (portfolios.length === 0) {
      setValuations({});
      return;
    }
    const ids = portfolios.map((p) => p.id);
    const request = ++valRequestRef.current;
    const controller = new AbortController();
    setValuations((prev) => {
      const next: Record<number, CardValuationState> = {};
      for (const id of ids) {
        next[id] = prev[id]?.status === "ready" ? prev[id] : { status: "loading" };
      }
      return next;
    });
    void (async () => {
      try {
        const res = await getHubValuations(ids, { signal: controller.signal });
        if (request !== valRequestRef.current) return;
        const byId: Record<number, CardValuationState> = {};
        for (const id of ids) {
          byId[id] = { status: "error", message: "Нет данных оценки" };
        }
        for (const item of res.items ?? []) {
          byId[item.portfolio_id] = { status: "ready", data: item };
        }
        setValuations(byId);
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (request !== valRequestRef.current) return;
        const message = errorMessage(reason);
        const byId: Record<number, CardValuationState> = {};
        for (const id of ids) {
          byId[id] = { status: "error", message };
        }
        setValuations(byId);
      }
    })();
    return () => {
      controller.abort();
    };
  }, [portfolios]);

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
            <PortfolioHubCard
              key={p.id}
              portfolio={p}
              selected={selectedPortfolioId === p.id}
              valuation={valuations[p.id]}
              onRename={() => void onRename(p.id, p.name)}
              onDelete={() => void onDelete(p.id, p.name)}
            />
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

      <p className="muted" style={{ marginTop: "1.5rem" }}>
        Кандидат Kraken и Shadow остаются отдельными контурами — это не пользовательские портфели.{" "}
        <Link to="/portfolio/candidate">Собрать портфель (кандидат модели)</Link>
      </p>
    </section>
  );
}
